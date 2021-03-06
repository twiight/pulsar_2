# -*- coding: utf-8 -*-
"""
Created on Sun Sep 20 18:13:40 2015
@author: Felix Darvas
@author: baotong
compute the Gregory-Laredo algorithm on arival times
This function computes the likelihood of a set of arrival times originating
from a periodic system rather than constant rate (poisson) background noise
based on
Gregory, P. C. and Thomas. J. Loredo, 1992,
"A New Method For The Detection Of A Periodic Signal Of Unknown Shape And Period"
in
The Astrophysical Journal, Astrophysical J., 398, p.146
inputs:
Tlist    -  list of arrival times, numpy int array
m_max    -  max number of bins typically 12-15, we use 12 as default
w_range  -  frequency range to scan numpy float array of frequency values
           default is  w_lo=20*pi/T at delta w = pi/T to w_hi=pi*N/T
           where N=#arrival times, T=observation time
ni       - number of integration steps, default ni=10
parallel - use parallel execution - default is off
outut:
O_period - Odds ratio for a periodic process vs. constant rate process
p_period - probability of a periodic process 0<=p_period<=1
m_opt    - optimal bin size 1<= m_opt <=m_max
S        - The probability spectrum
w        - The frequency range for S
w_peak   - the expected frequency of the process
w_conf   - 95% confidence interval of w_peak
"""
import numpy as np
import matplotlib.pyplot as plt
import multiprocessing as mp
import functools
import datetime
#import read_data as data
#import read_data_gc as data
starttime = datetime.datetime.now()
#T = 1618692.94

def get_T_in_mbins(epoch_file,w,m,fi):
    T=2*np.pi/w
    T_in_perbin = np.zeros(m)
    # 每个bin的总积分时间
    tbin = T/m
    # 每个bin的时间长度
    epoch_info = epoch_file
    t_start = epoch_info[:, 0]
    t_end = epoch_info[:, 1]
    # t_start=[epoch_info[0]]
    # t_end = [epoch_info[1]]
    N_bin_t_start=t_start/tbin+m*fi/(2*np.pi)
    N_bin_t_end=t_end/tbin+m*fi/(2*np.pi)
    intN_bin_t_start=np.floor(N_bin_t_start)+1
    intN_bin_t_end=np.floor(N_bin_t_end)
    intN_bin_t_start=intN_bin_t_start.astype(int)
    intN_bin_t_end=intN_bin_t_end.astype(int)
    for i in range(len(N_bin_t_start)):
        if intN_bin_t_end[i]>=intN_bin_t_start[i]:
            T_in_perbin+=int((intN_bin_t_end[i]-intN_bin_t_start[i])/m)*tbin
            #print(intN_bin_t_start[i]-1)
            T_in_perbin[np.mod(intN_bin_t_start[i],m)-1]+=(intN_bin_t_start[i]-N_bin_t_start[i])*tbin
            T_in_perbin[np.mod(intN_bin_t_end[i],m)]+=(N_bin_t_end[i]-intN_bin_t_end[i])*tbin
            rest=np.mod(intN_bin_t_end[i]-intN_bin_t_start[i],m)
            for k in range(rest):
                T_in_perbin[int(np.mod((intN_bin_t_start[i] + k), m))] += tbin
            #print(rest)
        else:
            T_in_perbin[np.mod(intN_bin_t_start[i],m)-1]+=(N_bin_t_end[i]-N_bin_t_start[i])*tbin
    return T_in_perbin

def compute_bin(Tlist, m, w, fi):
    n = np.zeros(m, 'int')
    j = np.floor(m * np.mod(w * Tlist + fi, 2 * np.pi) / (2 * np.pi))
    j.astype(int)
    for u in range(0, m):
        n[u] = np.size(np.extract(j == u, j))
    return n

def compute_factor(N, m, v):
    # compute m^N *(N+m-1)! / (2pi*v*(m-1)!
    # which is used to scale the multiplicity function (see eqn.5.25 of the paper )
    # we return the log of the integral scale here to avoid numerical overflow
    f1 = N * np.log(m)  # log of m^N
    f2 = np.sum(np.log(np.arange(1, N + m)))  # log of (N+m-1)!
    #f3 = np.sum(np.log(np.arange(1, m + 1)))  # log of m!
    f3 = np.sum(np.log(np.arange(1, m )))
    #should be (m-1)! --Tong
    f = f1 + f3 - f2 - np.log(2 * np.pi * v)
    return f

def filter_energy(time,energy,band):
    T=time
    E=energy
    i=0
    if len(time)!=len(energy):
        print('error')
        return None
    else:
        while i <len(E):
            if E[i]<band[0] or E[i]>band[1]:
                E=np.delete(E,i)
                T=np.delete(T,i)
            else:
                i+=1
    return T

def precompute_binmult(N):
    #return [lg(n!) for n in range(1,N)], 第一项忽略
    # precompute all potential bin factorials
    fbin = np.zeros(int(N) + 1)
    for i in range(2, int(N) + 1):  # n=0 -> define log(n)=0, n=1, log(n)=0, so no need to compute n=0,1
        fbin[i] = fbin[i - 1] + np.log(i)
    return fbin

def compute_S(epoch_file,Tlist,w,m,fi):
    n = compute_bin(Tlist, m, w, fi)
    tao=get_T_in_mbins(epoch_file,w,m,fi)
    s_wfi=tao/(sum(tao)/m)
    ln_S_wfi=-sum(n*np.log(s_wfi))
    return ln_S_wfi

def compute_W_scaled(Tlist, m, w, fi, factor, fbin,epoch_file):
    # compute the scaled multiplicity 1/Wm(w,fi) (see eqn. 5.25)
    # actually, it compute only n1!n2!...nm!,cause N! is been reduced in compute_factor --Tong
    # note that for large arrival time numbers the multiplicity becomes
    # excessively large. Since W_m(fi,w) is never needed explicitly,
    # we use the scaled version.
    # input factor is the log of the actual factor
    n = compute_bin(Tlist, m, w, fi)  # find bin histogram for a given bin number m, frequency w and fi
    f = 0
    for i in range(0, m):
        # f=f+np.sum(np.log(np.arange(2,n[i]+1)))
        f = f + fbin[n[i]]
    ln_S_wfi=compute_S(epoch_file,Tlist,w,m,fi)
    y = np.exp(f + factor+ln_S_wfi)
    #if y >1:
        #print(y)
        #print(f)
        #print(factor)

    return y


def compute_Om1(w, Tlist, m, factor, fbin, ni,epoch_file):
    # compute  specific odds-ratios (eqn. 5.25)
    p = np.arange(0, ni) / float(ni) * 2 * np.pi / m
    #p 即为输入的fi
    # intgration range, only integrate over a single bin, as values of the integral repeat over bins
    y = np.zeros(np.size(p), 'float')  # array to hold values of W_scaled over the integration range
    for i in range(0, np.size(y)):
        y[i] = compute_W_scaled(Tlist, m, w, p[i], factor, fbin,epoch_file)
    return np.trapz(y, p) * m  # return intregrated W_Scaled


def compute_Om1wPar(Tlist, m_max, w, fa, fbin, ni,epoch_file):  # compute odds-ratios for bins and frequencies
    # parallel version
    Om1w = np.zeros((m_max, np.size(w)), 'float')  # odds ratio matrix
    pool = mp.Pool()  # use all workers
    for m in range(0, m_max):
        Om1w[m, :] = pool.map(functools.partial(compute_Om1, Tlist=Tlist, m=(m + 1), factor=fa[m], fbin=fbin, ni=ni,epoch_file=epoch_file), w)
    return Om1w


def compute_Om1w(Tlist, m_max, w, fa, fbin, ni,epoch_file):  # compute odds-ratios for bins and frequencies
    Om1w = np.zeros((m_max, np.size(w)), 'float')  # odds ratio matrix
    for m in range(0, m_max):
        for wi in range(0, np.size(w)):
            Om1w[m, wi] = compute_Om1(w[wi], Tlist, m + 1, fa[m], fbin, ni,epoch_file=epoch_file)
    return Om1w


def compute_GL(Tlist, epoch_file,m_max=20, w_range=None, ni=10, parallel=False):
    # initialize output values
    O_period = None
    p_period = None
    m_opt = None
    S = None
    w = None
    w_peak = None
    w_mean = None
    w_conf = None
    N = float(np.size(Tlist))  # need float value to avoid int/int
    if N > 0:
        # compute GL algorithm
        fbin = precompute_binmult(N)
        v = m_max - 1
        #T = float(np.max(Tlist))  # duration of the observation
        if w_range is None:  # use default frequencies
            w_hi = 5*np.pi * N / T  # max default frequency

            w_lo = np.minimum(20, N / 10) * np.pi / T  # min default frequency
            dw = np.pi / T / 10  # step size
            w = np.arange(w_lo, w_hi, dw)
            if np.size(w) < 2:
                print
                "error "
                raise ValueError('bad arrival time list')
        else:  # use user supplied frequency vector
            w = w_range
            w_hi = np.max(w_range)
            w_lo = np.min(w_range)
        if w_lo == 0:
            # cannot have w_lo =0
            print("minimum frequency cannot be 0!\n")
            return

        fa = np.zeros(m_max)
        for m in range(0, m_max):  # precompute factors for each m
            fa[m] = compute_factor(N, m + 1, v)
        if parallel:
            Om1w = compute_Om1wPar(Tlist, m_max, w, fa, fbin, ni,epoch_file)
        else:
            Om1w = compute_Om1w(Tlist, m_max, w, fa, fbin, ni,epoch_file)

        pw = 1./ (w*np.log(w_hi / w_lo))
        O1m = np.zeros(m_max)
        for i in range(0, m_max):  # intgreate odd ratios across frequencies
            O1m[i] = np.trapz(pw * Om1w[i], w)
        #print(Om1w[1])
        #print(O1m)
        m_opt = np.argmax(O1m) # find optimum bin number, i.e largest odds-ratio
        S = Om1w[m_opt] / w  # compute Spectral probability
        m_opt = m_opt + 1  # start bin index with 1
        C = np.trapz(S, w)  # compute normalization
        S = S / C  # normalized probability
        O_period = np.sum(O1m)  # integrated odds ratio
        p_period = O_period / (1 + O_period)  # likelihood of periodic event
        cdf = np.array(S)
        plt.semilogy()
        plt.step(w, cdf)
        plt.show()
        for i in range(0, np.size(S)):
            cdf[i] = np.trapz(S[0:i], w[0:i])
        wr = np.extract(np.logical_and(cdf > .025, cdf < .975), w)
        w_peak = w[np.argmax(S)]
        w_mean = np.trapz(S * w, w)
        if np.size(wr) > 0:
            w_conf = [np.min(wr), np.max(wr)]
        else:
            w_conf = [w_peak, w_peak]
        return O_period, p_period, m_opt, S, w, w_peak, w_mean, w_conf,cdf
    else:
        # throw an error
        print("No valid arrival time array provided!\n")
        return O_period, p_period, m_opt, S, w, w_peak, w_mean, w_conf,cdf

import sys
if __name__ == '__main__':
    compute_GL(Tlist, epoch_file,m_max=20, w_range=None, ni=10, parallel=False)
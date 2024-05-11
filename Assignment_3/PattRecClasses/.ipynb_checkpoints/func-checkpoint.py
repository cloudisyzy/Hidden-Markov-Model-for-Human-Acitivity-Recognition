import numpy as np
from .MarkovChain import MarkovChain
import os
import matplotlib.pyplot as plt
from collections import Counter


def load_data(path, averaging=True, window=2):
    ## load data from .csv file, moving average is conducted if averaging=True, MA order = window, default=2
    data = np.genfromtxt(path, delimiter=',', names=True)
    x = data['x']
    y = data['y']
    z = data['z']
    data = np.concatenate((x,y,z), axis=0).reshape(3,-1)
    
    if averaging == True:
        n, T = data.shape
        averaged_data = np.zeros((n, T))
        for t in range(T):
            start_index = max(0, t - window + 1)
            end_index = min(T, t + 1)
            averaged_data[:, t] = np.mean(data[:, start_index:end_index], axis=1)
        return averaged_data
    
    else:
        return data
    
    
def plot_fft(data, sample_rate):
    ## to observe how moving average affect the high frequency components 
    n, T = data.shape
    freq = np.fft.fftfreq(T, d=1/sample_rate)
    # Only show one (x) axis of data
    fft_vals = np.fft.fft(data[0])
    plt.figure(figsize=(10, 6))
    plt.plot(freq[:T // 2], np.abs(fft_vals)[:T // 2])
    plt.title('Frequency domain of the signal component x-axis')
    plt.xlabel('freq')
    plt.grid(True)
    plt.figure(figsize=(10, 6))
    plt.plot(data[0])
    plt.title('Time domain of the signal component x-axis')
    plt.xlabel('t')
    plt.grid(True)
    plt.show()
    

def compute_pX(observations, dists, scale=True):
    ## to estimate bj(x) in textbook, observations <=> x
    ##                                dists <=> distribution used to generate x
    ##                                likelihood <=> bj(x) for each distribution
    range_dim = observations.shape[1] if observations.ndim > 1 else observations.shape[0]
    unscaled_pX = []

    for dist in dists:
        pX_i = []
        for i in range(range_dim):
            if observations.ndim > 1:
                likelihood = dist.prob(observations[:,i])
            else:
                likelihood = dist.prob(observations[i])
            pX_i.append(likelihood)
        unscaled_pX.append(pX_i)

    unscaled_pX =  np.array(unscaled_pX)
    scaled_pX = unscaled_pX / np.max(unscaled_pX, axis=0) # scale as described in textbook

    if scale == True:
        return scaled_pX
    else:
        return unscaled_pX


def BaumWelch(q, A, dist, data):
    ## train HMM using Baum-Welch algorithm, equivalent to EM, data <=> observed seq
    ##                                dist <=> source distributions
    ##                                A <=> transition prob
    ##                                q <=> initial prob
    
    # Initialization
    mc = MarkovChain(q, A)
    pX = compute_pX(data, dist, scale=True)
    n_states = q.shape[0] # # of hidden states
    T = data.shape[1] # length of obersavations
    
    # Forward & Backward
    alpha_hat, c = mc.forward(pX)
    beta_hat = mc.backward(pX, c)
    # print(alpha_hat)
    # print(c)
    # print(beta_hat)
    
    # Compute Gamma
    gamma = np.zeros_like(alpha_hat) 
    for j in range(gamma.shape[0]):
        for t in range(gamma.shape[1]):
            gamma[j,t] = alpha_hat[j,t] * beta_hat[j,t] * c[t] # 5.63 
    # print(gamma)
            
    # Update q
    q_updated = gamma[:,0] / np.sum(gamma[:,0]) # 7.54 
    # print(q_updated)
    
    # Update A
    eps = np.zeros((n_states, n_states, T))
    eps_hat = np.zeros((n_states, n_states))
    for i in range(n_states):
        for j in range(n_states):
            for t in range(T-1):
                eps[i,j,t] = alpha_hat[i,t] * A[i,j] * pX[j,t+1] * beta_hat[j,t+1] # 6.19
            eps_hat[i,j] = np.sum(eps[i,j,:]) # 6.12
    A_updated = np.zeros_like(A)      
    denominator_A = np.sum(eps_hat, axis=1)
    for i in range(eps_hat.shape[0]):
        A_updated[i,:] = eps_hat[i,:] / denominator_A[i] # 6.13
    # print(A_updated)
        
    # Update B, equivalent to update the parameters of source distribution of each state
    ## Update Means
    mu_updated = np.zeros((n_states, dist[0].means.shape[0]))
    for i in range(n_states):
        temp = np.zeros_like(data)
        for t in range(T):
            temp[:,t] = gamma[i,t] * data[:,t]
        numerator_mu = np.sum(temp, axis=1)
        denominator_mu = np.sum(gamma[i,:], axis=0)
        mu_updated[i] = numerator_mu / denominator_mu # 7.70 
    # print(mu_updated)
    ## Update Covariances
    cov_updated = np.zeros((n_states, dist[0].cov.shape[0], dist[0].cov.shape[1]))
    for i in range(n_states):
        temp = np.zeros((data.shape[0], data.shape[0], T)) # data.shape[0] is equivalent to dist[0].cov.shape[0]
        for t in range(T):
            temp[:,:,t] = gamma[i,t] * ( (data[:,t]-mu_updated[i,:]).reshape(n_states, -1) * (data[:,t]-mu_updated[i,:]) )
        numerator_cov = np.sum(temp, axis=2)
        denominator_cov = np.sum(gamma[i,:], axis=0)
        cov_updated[i,:,:] = numerator_cov / denominator_cov # 7.70 
    # print(cov_updated)
    ## Update General Distributions
    dist_updated = []
    for i, state_dist in enumerate(dist):
        state_dist.means = mu_updated[i]
        state_dist.cov = cov_updated[i]
        dist_updated.append(state_dist)
    
    return q_updated, A_updated, dist_updated


def HMM_prediction(q, A, dist, data, decision=False):
    ## use HMM to predict the status of a given observation (data)
    ## decision=False -> return only predicted state seq (array consists of 1, 2, 3), decided by the argmax of the conditional prob of states given observations (gamma)
    ## decision=True -> return the hard decision of class (base on # of 1s, 2s, 3s) and state seq
    
    # Initialization
    prefix = np.load('PattRecClasses/prefix.npy')
    data = np.concatenate((prefix, data), axis=1)
    mc = MarkovChain(q, A)
    pX = compute_pX(data, dist, scale=True)
    
    # Forward & Backward
    alpha_hat, c = mc.forward(pX)
    beta_hat = mc.backward(pX, c)
    
    # Compute gamma, P of state # given observations
    gamma = np.zeros_like(alpha_hat) 
    for j in range(gamma.shape[0]):
        for t in range(gamma.shape[1]):
            gamma[j,t] = alpha_hat[j,t] * beta_hat[j,t] * c[t]
            
    pred_state_seq = np.argmax(gamma, axis=0) + 1
    
    if decision == False:
        return pred_state_seq
    else:
        count_state_freq = Counter(pred_state_seq)
        pred_class = count_state_freq.most_common(1)[0][0]
        return pred_state_seq, pred_class


def plot_prediction_HMM(state_seq, observations, size=(10, 6), ppi=120, title='Prediction of HMM Given Observations', save_path=None):
    ## plot the observation seq along with the predicted states in a single plot with two scales
    
    plt.figure(figsize=size, dpi=ppi)
    
    ax1 = plt.gca()
    ax1.plot(observations[0], 'g', label='X-axis')
    ax1.plot(observations[1], 'b', label='Y-axis')
    ax1.plot(observations[2], 'grey', label='Z-axis')
    ax1.set_ylim([-15, 15])
    ax1.set_ylabel('Amplitude of Accelerometer Measurements')
    ax1.yaxis.label.set_color('blue')
    ax1.tick_params(axis='y', colors='blue')
    ax1.legend(loc='upper left')

    ax2 = ax1.twinx()
    ax2.plot(state_seq, 'r.', label='Predicted State')
    ax2.set_ylim([0.5, 3.5])
    ax2.set_ylabel('Predicted State Number')
    ax2.yaxis.label.set_color('red')
    ax2.tick_params(axis='y', colors='red')
    ax2.set_yticks([1, 2, 3])
    ax2.legend(loc='upper right') 

    ax1.set_xlabel('Time')
    plt.title(title)
    plt.grid()
    
    if save_path:
        plt.savefig(save_path, transparent=False, facecolor='w')

    plt.show()

    
# def BaumWelch(q, A, dist, data):
    
#     # Initialization
#     mc = MarkovChain(q, A)
#     pX = compute_pX(data, dist, scale=True)
#     n_states = q.shape[0] # # of hidden states
#     T = data.shape[1] # length of obersavations
    
#     # Forward & Backward
#     alpha_hat, c = mc.forward(pX)
#     beta_hat = mc.backward(pX, c)
#     # print(alpha_hat)
#     # print(c)
#     # print(beta_hat)
    
#     # Compute Gamma
#     gamma = np.zeros_like(alpha_hat) 
#     for j in range(gamma.shape[0]):
#         for t in range(gamma.shape[1]):
#             gamma[j,t] = alpha_hat[j,t] * beta_hat[j,t] * c[t] # 5.63 !!! gamma 和参考的算的不一样，怀疑是参考错误，尤其在c[t]的使用上,如果将参考中c[t]改为c[j],则结果相同，不过为转置
#     # print(gamma)
            
#     # Update q
#     q_updated = gamma[:,0] / np.sum(gamma[:,0]) # 7.54 !!! gamma 和参考的算的不一样，q肯定不一样，如果将参考中c[t]改为c[j],则结果相同
#     # print(q_updated)
    
#     # Update A
#     eps = np.zeros((n_states, n_states, T))
#     eps_hat = np.zeros((n_states, n_states))
#     for i in range(n_states):
#         for j in range(n_states):
#             for t in range(T-1):
#                 eps[i,j,t] = alpha_hat[i,t] * A[i,j] * pX[j,t+1] * beta_hat[j,t+1] # 6.19
#             eps_hat[i,j] = np.sum(eps[i,j,:]) # 6.12
#     A_updated = np.zeros_like(A)      
#     denominator_A = np.sum(eps_hat, axis=1)
#     for i in range(eps_hat.shape[0]):
#         A_updated[i,:] = eps_hat[i,:] / denominator_A[i] # 6.13
#     # print(A_updated)
        
#     # Update B, equivalent to update the parameters of source distribution of each state
#     ## Update Means
#     mu_updated = np.zeros((n_states, dist[0].means.shape[0]))
#     for i in range(n_states):
#         temp = np.zeros_like(data)
#         for t in range(T):
#             temp[:,t] = gamma[i,t] * data[:,t]
#         numerator_mu = np.sum(temp, axis=1)
#         denominator_mu = np.sum(gamma[i,:], axis=0)
#         mu_updated[i] = numerator_mu / denominator_mu # 7.70 ！！！gamma 和参考的算的不一样，mu肯定不一样，如果将参考中c[t]改为c[j],则结果相同
#     # print(mu_updated)
    
#     ## Update Covariances
#     cov_updated = np.zeros((n_states, dist[0].cov.shape[0], dist[0].cov.shape[1]))
#     for i in range(n_states):
#         temp = np.zeros((data.shape[0], data.shape[0], T)) # data.shape[0] is equivalent to dist[0].cov.shape[0]
#         for t in range(T):
#             temp[:,:,t] = gamma[i,t] * ( (data[:,t]-mu_updated[i,:]).reshape(n_states, -1) * (data[:,t]-mu_updated[i,:]) )
#         numerator_cov = np.sum(temp, axis=2)
#         denominator_cov = np.sum(gamma[i,:], axis=0)
#         cov_updated[i,:,:] = numerator_cov / denominator_cov # 7.70 ！！！gamma 和参考的算的不一样，cov肯定不一样，如果将参考中c[t]改为c[j],则结果相同
#     # print(cov_updated)
    
#     return q_updated, A_updated, mu_updated, cov_updated



# def dist_update(old_dist, new_mu, new_cov):
#     new_dist = []
#     for i, state_dist in enumerate(old_dist):
#         state_dist.means = new_mu[i]
#         state_dist.cov = new_cov[i]
#         new_dist.append(state_dist)
    
#     return new_dist
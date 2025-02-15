

import numpy as np
from copy import deepcopy
from value_function import ValueFunction
import pandas as pd
from replay_buffer import Dataset
import deepdish as dd
from tqdm import tqdm

class Program(object):
    def __init__(self, constraints, action_space_dim, best_response_algorithm, online_convex_algorithm, fitted_off_policy_evaluation_algorithm, exact_policy_algorithm, lambda_bound = 1., epsilon = .01, env= None, max_iterations=None, num_frame_stack=None, pic_size=None):
        '''
        This is a problem of the form: min_pi C(pi) where G(pi) < eta.

        dataset: list. Will be {(x,a,x',c(x,a), g(x,a)^T)}
        action_space_dim: number of dimension of action space
        dim: number of constraints
        best_response_algorithm: function which accepts a |A| dim vector and outputs a policy which minimizes L
        online_convex_algorithm: function which accepts a policy and returns an |A| dim vector (lambda) which maximizes L
        lambda_bound: positive int. l1 bound on lambda |lambda|_1 <= B
        constraints:  |A| dim vector
        epsilon: small positive float. Denotes when this problem has been solved.
        env: The environment. Used for exact policy evaluation to test fittedqevaluation
        '''

        self.dataset = Dataset(num_frame_stack, pic_size, (len(constraints) + 1,) )
        self.constraints = constraints
        self.C = ValueFunction()
        self.G = ValueFunction()
        self.C_exact = ValueFunction()
        self.G_exact = ValueFunction()
        self.action_space_dim = action_space_dim
        self.dim = len(constraints)
        self.lambda_bound = lambda_bound
        self.epsilon = epsilon
        self.best_response_algorithm = best_response_algorithm
        self.online_convex_algorithm = online_convex_algorithm
        self.exact_lambdas = []
        self.fitted_off_policy_evaluation_algorithm = fitted_off_policy_evaluation_algorithm
        self.exact_policy_evaluation = exact_policy_algorithm
        self.env = env
        self.prev_lagrangians = []
        self.max_iterations = max_iterations if max_iterations is not None else np.inf
        self.iteration = -2

    def best_response(self, lamb, idx=0, **kw):
        '''
        Best-response(lambda) = argmin_{pi} L(pi, lambda) 
        '''
        # dataset = deepcopy(self.dataset)
        self.dataset.calculate_cost(lamb)
        policy = self.best_response_algorithm.run(self.dataset, **kw)
        return policy

    def online_algo(self):
        '''
        No regret online convex optimization routine
        '''
        gradient = self.G.last() - self.constraints
        lambda_t = self.online_convex_algorithm.run(gradient)

        return lambda_t

    def lagrangian(self, C, G, lamb):
        # C(pi) + lambda^T (G(pi) - eta), where eta = constraints, pi = avg of all pi's seen
        return C.avg() + np.dot(lamb, (G.avg() - self.constraints))

    def max_of_lagrangian_over_lambda(self):
        '''
        The maximum of C(pi) + lambda^T (G(pi) - eta) over lambda is
        B*e_{k+1}, all the weight on the phantom index if G(pi) < eta for all constraints
        B*e_k otherwise where B is the l1 bound on lambda and e_k is the standard
        basis vector putting full mass on the constraint which is violated the most
        '''

        # Actual calc
        maximum = np.max(self.G.avg() - self.constraints)
        index = np.argmax(self.G.avg() - self.constraints) 

        if maximum > 0:
            lamb = self.lambda_bound * np.eye(1, self.dim, index)
        else:
            lamb = np.zeros(self.dim)
            lamb[-1] = self.lambda_bound

        maximum = np.max(self.G_exact.avg() - self.constraints)
        index = np.argmax(self.G_exact.avg() - self.constraints) 

        print('Lambda maximizing lagrangian: %s' % lamb)
        return self.lagrangian(self.C, self.G, lamb)

    def min_of_lagrangian_over_policy(self, lamb):
        '''
        This function evaluates L(best_response(avg_lambda), avg_lambda)
        '''
        
        # print 'Calculating best-response(lambda_avg)'
        best_policy, values = self.best_response(lamb, idx=1, desc='FQI pi(lambda_avg)', exact=self.exact_policy_evaluation)

        if self.env.env_type=='car':
            dataset_length = len(self.dataset)
            batch_size = 512
            num_batches = int(np.ceil(dataset_length/float(batch_size)))

            actions = []
            all_idxs = list(range(dataset_length))
            print('Creating best_response(x\')') 
            for i in tqdm(list(range(num_batches))):
                idxs = all_idxs[(batch_size*i):(batch_size*(i+1))]
                states = np.rollaxis(self.dataset['frames'][self.dataset['next_states'][idxs]],1,4)
                actions.append(best_policy([states], x_preprocessed=True))

            self.dataset.data['pi_of_x_prime'] = np.hstack(actions)


        # print 'Calculating C(best_response(lambda_avg))'
        # dataset = deepcopy(self.dataset)
        C_br, values = self.fitted_off_policy_evaluation_algorithm.run(best_policy,'c', self.dataset, desc='FQE C(pi(lambda_avg))')

        
        # print 'Calculating G(best_response(lambda_avg))'
        G_br = []
        for i in range(self.dim-1):
            # dataset = deepcopy(self.dataset)
            output, values = self.fitted_off_policy_evaluation_algorithm.run(best_policy,'g', self.dataset,  desc='FQE G_%s(pi(lambda_avg))'% i, g_idx=i)
            G_br.append(output)
        G_br.append(0)
        G_br = np.array(G_br)

        if self.env is not None:
            print('Calculating exact C, G policy evaluation')
            exact_c, exact_g, performance = self.exact_policy_evaluation.run(best_policy, to_monitor=True)
            if self.env.env_type == 'car': exact_g = np.array(exact_g)[[-1,2]]

        print()
        print('C(pi(lambda_avg)) Exact: %s, Evaluated: %s, Difference: %s' % (exact_c, C_br, np.abs(C_br-exact_c)))
        print('G(pi(lambda_avg)) Exact: %s, Evaluated: %s, Difference: %s' % (exact_g, G_br[:-1], np.abs(G_br[:-1]-exact_g)))
        print('Mean lambda: %s' % lamb)
        print() 

        return C_br + np.dot(lamb, (G_br - self.constraints)), C_br, G_br, exact_c, exact_g

    def update(self, policy, values, iteration):
        
        if self.env.env_type=='car':
            dataset_length = len(self.dataset)
            batch_size = 512
            num_batches = int(np.ceil(dataset_length/float(batch_size)))

            actions = []
            all_idxs = list(range(dataset_length))
            print('Creating pi_%s(x\')' % iteration) 
            for i in tqdm(list(range(num_batches))):
                idxs = all_idxs[(batch_size*i):(batch_size*(i+1))]
                states = np.rollaxis(self.dataset['frames'][self.dataset['next_states'][idxs]],1,4)
                actions.append(policy([states], x_preprocessed=True))

            self.dataset.data['pi_of_x_prime'] = np.hstack(actions)

        #update C
        # dataset = deepcopy(self.dataset)
        C_pi, eval_values = self.fitted_off_policy_evaluation_algorithm.run(policy,'c', self.dataset, desc='FQE C(pi_%s)' %  iteration)
        self.C.append(C_pi, policy)
        C_pi = np.array(C_pi)
        self.C.add_exact_values(values)
        self.C.add_eval_values(eval_values, 0)

        #update G
        G_pis = []       
        for i in range(self.dim-1):        
            # dataset = deepcopy(self.dataset)
            output, eval_values = self.fitted_off_policy_evaluation_algorithm.run(policy,'g', self.dataset, desc='FQE G_%s(pi_%s)' %  (i, iteration), g_idx = i)
            G_pis.append(output)
            self.G.add_eval_values(eval_values, i)
        G_pis.append(0)
        self.G.append(G_pis, policy)
        G_pis = np.array(G_pis)
        

        # Get Exact Policy
        exact_c, exact_g, performance = self.calc_exact(policy)

        print()
        print('C(pi_%s) Exact: %s, Evaluated: %s, Difference: %s' % (iteration, exact_c, C_pi, np.abs(C_pi-exact_c)))
        print('G(pi_%s) Exact: %s, Evaluated: %s, Difference: %s' % (iteration, exact_g, G_pis[:-1], np.abs(G_pis[:-1]-exact_g)))
        print() 

    def calc_exact(self, policy):
        print('Calculating exact C, G policy evaluation')
        exact_c, exact_g, performance = self.exact_policy_evaluation.run(policy, to_monitor=True)
        if self.env.env_type == 'car':exact_g = np.array(exact_g)[[-1,2]] 
        self.C_exact.add_exact_values([performance])
        self.C_exact.append(exact_c)
        self.G_exact.append(np.hstack([exact_g, np.array([0])]))
        return exact_c, exact_g, performance

    def collect(self, *data, **kw):
        '''
        Add more data
        '''
        if ('start' in kw) and kw['start']: 
            self.dataset.start_new_episode(*data)
        else:
            self.dataset.append(*data)

    def finish_collection(self, env_type):
        # preprocess
        self.dataset.preprocess(env_type)
        dd.io.save('%s.h5' % env_type, self.dataset.data)


    def is_over(self, policies, lambdas, infinite_loop=False, calculate_gap = True, results_name='results.csv', policy_improvement_name='policy_improvement.h5'):
        # lambdas: list. We care about average of all lambdas seen thus far
        # If |max_lambda L(avg_pi, lambda) - L(best_response(avg_lambda), avg_lambda)| < epsilon, then done
        self.iteration += 1

        if calculate_gap:
            if len(lambdas) == 0: return False
            if len(lambdas) == 1: 
                #use stored values
                x = self.max_of_lagrangian_over_lambda()
                y = self.C.last() + np.dot(lambdas[-1], (self.G.last() - self.constraints))
                c_br, g_br, c_br_exact, g_br_exact = self.C.last(), self.G.last(), self.C_exact.last(), self.G_exact.last()[:-1]
            else:
                x = self.max_of_lagrangian_over_lambda()
                y,c_br, g_br, c_br_exact, g_br_exact = self.min_of_lagrangian_over_policy(np.mean(lambdas, 0))
                if self.env.env_type == 'car': g_br_exact = g_br_exact

            difference = x-y
            
            c_exact, g_exact = self.C_exact.avg(), self.G_exact.avg()[:-1]
            c_approx, g_approx = self.C.avg(), self.G.avg()[:-1]

            print('actual max L: %s, min_L: %s, difference: %s' % (x,y,x-y))
            print('Average policy. C Exact: %s, C Approx: %s' % (c_exact, c_approx))
            print('Average policy. G Exact: %s, G Approx: %s' % (g_exact, g_approx))
        else:
            if len(lambdas) == 0: return False
            c_exact, g_exact = self.C_exact.avg(), self.G_exact.avg()[:-1]
            c_approx, g_approx = self.C.avg(), self.G.avg()[:-1]
            x = 0
            y,c_br, g_br, c_br_exact, g_br_exact = 0, 0, [0]*(len(self.constraints)), 0, [0]*(len(self.constraints)-1)

        self.prev_lagrangians.append(np.hstack([self.iteration, x, y, c_exact, g_exact, c_approx, g_approx, self.C_exact.last(), self.G_exact.last()[:-1], self.C.last(), self.G.last()[:-1], lambdas[-1][:-1], c_br_exact, g_br_exact, c_br, g_br[:-1]  ]))

        self.save(results_name, policy_improvement_name)
        if infinite_loop:
            # Run forever to gather long curve for experiment
            return False
        else:
            if difference < self.epsilon:
                return True
            elif self.iteration >= self.max_iterations:
                return True
            else: 
                return False

    def save(self, results_name, policy_improvement_name):
        

        labels = []
        for i in range(len(self.constraints)-1): 
            labels.append(['g_exact_avg_%s' % i, 
                           'g_avg_%s' % i, 
                           'g_pi_exact_%s' % i, 
                           'g_pi_%s' % i, 
                           'g_br_exact_%s' % i, 
                           'g_br_%s' % i,
                           'lambda_%s' % i])

        labels = np.array(labels).T.tolist()
        df = pd.DataFrame(self.prev_lagrangians, columns=np.hstack(['iteration', 'max_L', 'min_L', 'c_exact_avg', labels[0], 'c_avg', labels[1], 'c_pi_exact', labels[2], 'c_pi', labels[3], labels[6], 'c_br_exact', labels[4], 'c_br', labels[5]]))
        df.to_csv(results_name, index=False)

        data = {}
        data['c_performance'] = self.C_exact.exact_values
        data['c_eval'] = self.C.eval_values
        data['g_eval'] = self.G.eval_values
        data['g_exacts'] = [x.tolist() for x in self.G_exact.prev_values]
        data['c_exacts'] = [x.tolist() for x in self.C_exact.prev_values]
        data['c_eval_actuals'] = self.C.exact_values
        dd.io.save(policy_improvement_name, data)



# class Dataset(Buffer):
#     def __init__(self, constraints, action_dim, num_frame_stack):
#         num_frame_stack=1,
#         buffer_size=10000,
#         min_buffer_size_to_train=1000,


#         # self.data = {'x':[], 'a':[], 'x_prime':[], 'c':[], 'g':[], 'done':[], 'cost':[]}
#         self.episodes = [Episode(constraints, action_dim)]
#         self.constraints = constraints
#         self.action_dim = action_dim
#         self.max_trajectory_length = 0

#     def append(self, *args):
#         if not self.episodes[-1].is_over():
#             self.episodes[-1].append(*args)
#         else:
#             self.episodes.append(Episode(self.constraints, self.action_dim))
#             self.episodes[-1].append(*args)

#         # update max_trajectory_length
#         if self.episodes[-1].get_length() > self.max_trajectory_length:
#             self.max_trajectory_length = self.episodes[-1].get_length()
        
#     def get_max_trajectory_length(self):
#         return self.max_trajectory_length
        
#     def __getitem__(self, key):
#         return np.array(self.data[key])

#     def __setitem__(self, key, item):
#         self.data[key] = item

#     def __len__(self):
#         return len(self.data['x'])

#     def preprocess(self, env_type):
#         for key in self.data:
#             if env_type == 'lake':
#                 if key in ['g']:
#                     try:
#                         self.data[key] = np.vstack([x[key] for x in self.episodes]).tolist()
#                     except:
#                         self.data[key] = np.hstack([x[key] for x in self.episodes]).tolist()
#                 else:
#                     self.data[key] = np.hstack([x[key] for x in self.episodes]).tolist()
#             elif env_type == 'car':
#                 if key in ['g', 'x', 'x_prime']:
#                     try:
#                         self.data[key] = np.vstack([x[key] for x in self.episodes]).tolist()
#                     except:
#                         self.data[key] = np.hstack([x[key] for x in self.episodes]).tolist()
#                 else:
#                     self.data[key] = np.hstack([x[key] for x in self.episodes]).tolist()
#             else:
#                 raise
#         [x.get_state_action_pairs(env_type) for x in self.episodes]
#         self.get_state_action_pairs(env_type)

#     def get_state_action_pairs(self, env_type=None):
#         if 'state_action' in self.data:
#             return self.data['state_action']
#         else:
#             if env_type == 'lake':
#                 pairs = np.vstack([np.array(self.data['x']), np.array(self.data['a']) ]).T
#             elif env_type == 'car':
#                 pairs = [np.array(self.data['x']), np.array(self.data['a']).reshape(1,-1).T ]
#             self.data['state_action'] = pairs

#     def calculate_cost(self, lamb):

#         costs = np.array(self.data['c'] + np.dot(lamb, np.array(self.data['g']).T))

#         # costs = costs/np.max(np.abs(costs))
#         self.data['cost'] = costs.tolist()

#         [x.calculate_cost(lamb) for x in self.episodes]

#     def set_cost(self, key, idx=None):
#         if key == 'g': assert idx is not None, 'Evaluation must be done per constraint until parallelized'

#         if key == 'c':
#             self.data['cost'] = self.data['c']
#             [x.set_cost('c') for x in self.episodes]
#         elif key == 'g':
#             # Pick the idx'th constraint
#             self.data['cost'] = np.array(self.data['g'])[:,idx].tolist()
#             [x.set_cost('g', idx) for x in self.episodes]
#         else:
#             raise


# class Episode(object):
#     def __init__(self, constraints, action_dim):
#         self.data = {'x':[], 'a':[], 'x_prime':[], 'c':[], 'g':[], 'done':[], 'cost':[]}
#         self.constraints = constraints
#         self.action_dim = action_dim
#         self.trajectory_length = 0

#     def is_over(self):
#         if len(self.data['done']):
#             return self.data['done'][-1]
#         else:
#             return False

#     def get_length(self):
#         return self.trajectory_length

#     def append(self, x, a, x_prime, c, g, done):
#         self.data['x'].append(x)
#         self.data['a'].append(a)
#         self.data['x_prime'].append(x_prime)
#         self.data['c'].append(c)
#         self.data['g'].append(g)
#         self.data['done'].append(done)
#         self.trajectory_length += 1      
        
#     def __getitem__(self, key):
#         return np.array(self.data[key])

#     def __setitem__(self, key, item):
#         self.data[key] = item

#     def __len__(self):
#         return len(self.data['x'])

#     def get_state_action_pairs(self, env_type=None):
#         if 'state_action' in self.data:
#             return self.data['state_action']
#         else:
#             if env_type == 'lake':
#                 pairs = np.vstack([np.array(self.data['x']), np.array(self.data['a'])]).T
#             elif env_type == 'car':
#                 pairs = [np.array(self.data['x']), np.array(self.data['a']).reshape(1,-1).T ]
#             else:
#                 raise
#             self.data['state_action'] = pairs

#     def calculate_cost(self, lamb):
#         costs = np.array(self.data['c'] + np.dot(lamb, np.array(self.data['g']).T))

#         # costs = costs/np.max(np.abs(costs))
#         self.data['cost'] = costs.tolist()

#     def set_cost(self, key, idx=None):
#         if key == 'g': assert idx is not None, 'Evaluation must be done per constraint until parallelized'

#         if key == 'c':
#             self.data['cost'] = self.data['c']
#         elif key == 'g':
#             # Pick the idx'th constraint
#             self.data['cost'] = np.array(self.data['g'])[:,idx].tolist()
#         else:
#             raise





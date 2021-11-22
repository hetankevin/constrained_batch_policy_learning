
from DQN import DeepQLearning
from env_nn import *

class LakeDQN(DeepQLearning):
    def __init__(self, *args, **kw):
        holes, goals = kw['position_of_holes'], kw['position_of_goals']
        del kw['position_of_holes']
        del kw['position_of_goals']

        self.min_epsilon = kw['min_epsilon']
        self.initial_epsilon = kw['initial_epsilon']
        self.epsilon_decay_steps = kw['epsilon_decay_steps']
        for key in ['min_epsilon', 'initial_epsilon', 'epsilon_decay_steps']:
            if key in kw: del kw[key]

        super(LakeDQN, self).__init__(*args, **kw)
        
        for key in ['action_space_map','max_time_spent_in_episode','num_iterations','sample_every_N_transitions','batchsize','copy_over_target_every_M_training_iterations', 'buffer_size', 'min_buffer_size_to_train', 'models_path']:
            if key in kw: del kw[key]

        kw['position_of_holes'],kw['position_of_goals']  = holes, goals
        self.state_space_dim = self.env.nS
        self.action_space_dim = self.env.nA
        self.Q = LakeNN(self.state_space_dim+self.action_space_dim, 1, [self.env.desc.shape[0], self.env.desc.shape[1]], self.action_space_dim, self.gamma, **kw)
        self.Q_target = LakeNN(self.state_space_dim+self.action_space_dim, 1, [self.env.desc.shape[0], self.env.desc.shape[1]], self.action_space_dim, self.gamma, **kw)

    def sample_random_action(self):
        '''
        Uniform random
        '''
        return np.random.choice(self.action_space_dim)

    # def epsilon(self, epoch=None, total_steps=None):
    #     return 1./(total_steps/100 + 3)
    def epsilon(self, epoch=None, total_steps=None):
        if epoch >= self.epsilon_decay_steps:
            return self.min_epsilon
        else:
            alpha = epoch / float(self.epsilon_decay_steps)
            current_epsilon = self.initial_epsilon * (1-alpha) + self.min_epsilon * (alpha)
            return current_epsilon

class CarDQN(DeepQLearning):
    def __init__(self, *args, **kw):
        
        self.gas_actions = None

        self.min_epsilon = kw['min_epsilon']
        self.initial_epsilon = kw['initial_epsilon']
        self.epsilon_decay_steps = kw['epsilon_decay_steps']
        self.action_space_dim = kw['action_space_dim']
        for key in ['action_space_dim', 'min_epsilon', 'initial_epsilon', 'epsilon_decay_steps']:
            if key in kw: del kw[key]

        super(CarDQN, self).__init__(*args, **kw) 
        for key in ['action_space_map','max_time_spent_in_episode','num_iterations','sample_every_N_transitions','batchsize','copy_over_target_every_M_training_iterations', 'buffer_size', 'min_buffer_size_to_train', 'models_path']:
            if key in kw: del kw[key]

        from config_car import state_space_dim
        self.state_space_dim = state_space_dim
        self.Q = CarNN(self.state_space_dim, self.action_space_dim, self.gamma, **kw)
        self.Q_target = CarNN(self.state_space_dim, self.action_space_dim, self.gamma, **kw)

    def sample_random_action(self):
        '''
        Biased (toward movement) random
        '''
        if self.gas_actions is None:
            self.gas_actions = {key:val[1] == 1 and val[2] == 0 for key,val in self.action_space_map.items()}

        action_weights = 14. * np.array(list(self.gas_actions.values())) + 1.0
        action_weights /= np.sum(action_weights)

        return np.random.choice(list(self.gas_actions.keys()), p=action_weights)
        # return np.random.choice(self.action_space_dim)

    def epsilon(self, epoch=None, total_steps=None):
        if epoch >= self.epsilon_decay_steps:
            # return max(.08*((2000-epoch)/1000), 0.) + .02
            return self.min_epsilon
        else:
            alpha = epoch / float(self.epsilon_decay_steps)
            current_epsilon = self.initial_epsilon * (1-alpha) + self.min_epsilon * (alpha)
            return current_epsilon
        







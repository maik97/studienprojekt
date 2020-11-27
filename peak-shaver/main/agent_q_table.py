import sys

import numpy as np
import pandas as pd
import random
import h5py

import gym
from gym import spaces

from datetime import datetime
from collections import deque
from tqdm import tqdm

import schaffer
from wahrsager import wahrsager
from common_env import common_env
from reward_maker import reward_maker
from common_func import try_training_on_gpu, max_seq, mean_seq

class Q_Learner:
    """
    Basic Q-Agent that uses a Q-Table
    
    Args:
        env (object): Takes in a GYM environment, use the common_env to simulate the HIPE-Dataset.
        memory (object): Takes in degue object: deque(maxlen=x)
        gamma (float): Factor that determines the importance of futue Q-values, value between 0 and 1
        epsilon (float): Initial percent of random actions, value between 0 and 1
        epsilon_min (float): Minimal percent of random actions, value between 0 and 1
        epsilon_decay (float): Factor by which epsilon decays, value between 0 and 1
        lr (float): Sets the learning rate of the RL-Agent
        tau (float): Factor for copying weights from model network to target network
        Q_table (array): Initial Q-Table, all values should be set to zero
    """
    def __init__(self, env, memory, gamma=0.85, epsilon=0.8, epsilon_min=0.1, epsilon_decay=0.999996, lr=0.5, tau=0.125, Q_table=np.zeros((22,22,22,22,22))):

        self.env            = env
        self.memory         = memory
        
        self.gamma          = gamma
        self.epsilon        = epsilon
        self.epsilon_min    = epsilon_min
        self.epsilon_decay  = epsilon_decay
        self.lr             = lr
        self.tau            = tau

        self.Q_table        = Q_table # jede Dimension jeweils ∈ [0,0.05,...,1]

        # Init Logging
        #self.LOGGER            = logger.Logger(DATENSATZ_PATH+'LOGS/agent_logging/'+NAME)

    def act(self, state):
        '''
        Function, in which the agent decides an action, either from greedy-policy or from prediction. Use this function when iterating through each step.
        
        Args:
            state (array): Current state at the step

        Returns:
            action, epsilon (tuple):
            
            action (integer): Action that was chosen by the agent
            
            epsilon (float): Current (decayed) epsilon
        '''
        self.epsilon *= self.epsilon_decay
        self.epsilon = max(self.epsilon_min, self.epsilon)
        if np.random.random() < self.epsilon:
            return self.env.action_space.sample(), self.epsilon  # = random action, zufallsparameter
        
        # state[0] : Power_demand
        # state[1] : SoC_SMS
        # state[2] : SoC_LiON
        state = state.reshape(len(cur_state),1).tolist()
        return np.argmax(self.Q_table[state][0]), self.epsilon # = action, zufallsparameter

    def remember(self, state, action, reward, new_state, done, step_counter_episode):
        '''
        Takes in all necessery variables for the learning process and appends those to the memory. Use this function when iterating through each step.

        Args:
            state (array): State at which the agent chose the action
            action (integer): Chosen action
            reward (float): Real reward for the action
            new_state (array): State after action is performed
            done (bool): If True the episode ends
            step_counter_episode (integer): Episode step at which the action was performed
        '''
        state = state.reshape(len(cur_state),1).tolist()
        new_state = new_state.reshape(len(cur_state),1).tolist()
        self.memory.append([state, action, reward, new_state, done, step_counter_episode])

    def replay(self, index_len):
        '''
        Training-Process for the DQN from past steps. Use this function after a few iteration-steps (best use is the number of index_len). Alternatively use this function at each step.

        Args:
            index_len (integer): Number of past states to learn from
        '''
        for i in range(index_len):
            # Lade Step von Simulation
            state, action, reward, new_state, done, step_counter_episode = self.memory[i] 
            
            if reward == None:
                #print('step_counter_episode',step_counter_episode)
                reward = self.env.get_multi_step_reward(step_counter_episode)
                #print(reward)

            if done:
                Q_future = reward
            else:
                Q_future = max(self.Q_table[new_state][0])
            
            state_and_action = np.append(state,action)
            state_and_action = state_and_action.reshape(len(state_and_action),1).tolist()
            
            Q_target = self.Q_table [state_and_action]
            self.Q_table[state_and_action] += (self.lr * (reward + (Q_future * self.gamma) - Q_target))
                    

    def save_agent(self, NAME, DATENSATZ_PATH, e):
        '''For saving the agents model at specific epoch. Make sure to not use this function at each epoch, since this will take up your memory space.

        Args:
            NAME (string): Name of the model
            DATENSATZ_PATH (string): Path to save the model
            e (integer): Takes the epoch-number in which the model is saved
        '''
        with h5py.File(DATENSATZ_PATH+'tables/'+NAME+'_{}.h5'.format(e), 'w') as hf:
            hf.create_dataset(NAME,  data=self.Q_table)



def main():
    '''
    Example of an RL-Agent that uses the basic Q-Table.
    '''
    # Logging-Namen:
    now            = datetime.now()
    NAME           = 'Q_Table'+now.strftime("_%d-%m-%Y_%H:%M:%S")
    DATENSATZ_PATH = '_BIG_D/'

    # Lade Dataframe:
    df = schaffer.alle_inputs_neu()[24:-12]
    
    #df['pred_mean']       = wahrsager(TYPE='MEAN').pred()[:-12]
    #df['pred_max']        = wahrsager(TYPE='MAX').pred()[:-12]
    #df['pred_normal']     = wahrsager(TYPE='NORMAL').pred()[:-12]
    #df['pred_max_labe']   = wahrsager(TYPE='MAX_LABEL_SEQ').pred()
    #df['pred_mean_label'] = wahrsager(TYPE='MEAN_LABEL_SEQ').pred()
    
    prediction_seq        = wahrsager(TYPE='SEQ', num_outputs=12).pred()
    df['max_pred_seq']    = max_seq(prediction_seq)
    #df['mean_pred_seq']   = mean_seq(prediction_seq)

    power_dem_arr  = schaffer.load_total_power()[24:-12]

    # Lade Reward-Maker:
    R_HORIZON = 0
    r_maker        = reward_maker(
                        COST_TYPE               = 'exact_costs',     # 'yearly_costs', 'max_peak_focus'
                        R_TYPE                  = 'savings_focus',   #'costs_focus', 'savings_focus'
                        M_STRATEGY              = 'single_step',              # None, 'sum_to_terminal', 'average_to_neighbour', 'recurrent_to_Terminal'
                        R_HORIZON               = None,         # 'episode', 'single_step', integer for multi-step
                        cost_per_kwh            = 0.2255,  # in €
                        LION_Anschaffungs_Preis = 34100,   # in €
                        LION_max_Ladezyklen     = 1000,
                        SMS_Anschaffungs_Preis  = 115000/3,# in €
                        SMS_max_Nutzungsjahre   = 20,      # in Jahre
                        Leistungspreis          = 102,     # in €
                        focus_peak_multiplier   = 4        # multiplier for max_peak costs
                        )

    # Lade Environment:
    env            = common_env(
                        df                   = df,
                        power_dem_arr        = power_dem_arr,
                        input_list           = ['norm_total_power','max_pred_seq'],
                        DATENSATZ_PATH       = DATENSATZ_PATH,
                        NAME                 = NAME,
                        max_SMS_SoC          = 12,
                        max_LION_SoC         = 54,
                        PERIODEN_DAUER       = 5,
                        ACTION_TYPE          = 'discrete',
                        num_discrete_obs     = 21,
                        num_discrete_actions = 22,
                        #action_space         = spaces.Discrete(22), # A ∈ [0,1]
                        #observation_space    = spaces.Box(low=0, high=21, shape=(4,1), dtype=np.float16),
                        reward_maker         = r_maker
                        )

    # Initilisiere Parameter für Target-Network
    update_num       = 1
    update_counter   = 0

    # Inititialsiere Epoch-Parameter:
    epochs           = 1000
    epochs_len       = len(df)
    
    num_warmup_steps = 100
    warmup_counter   = 0

    # Init Agent Parameter

    
    # Init Agent:
    Agent          = Q_Learner(
                        env            = env,
                        #memory         = deque(maxlen=(update_num)),
                        memory         = deque(maxlen=(R_HORIZON+update_num)),

                        gamma          = 0.85,
                        epsilon        = 0.8,
                        epsilon_min    = 0.1,
                        epsilon_decay  = 0.999996,
                        lr             = 0.5,
                        tau            = 0.125,

                        Q_table        = np.zeros((22,22,22,22,22)), # jede Dimension jeweils ∈ [0,0.05,...,1]
                        )

    print('Warmup-Steps per Episode:', num_warmup_steps)
    print('Training for',epochs,'Epochs')

    for e in range(epochs):
        #print('Epoch:', e)
        #tqdm.write('Starting Epoch: {}'.format(e))
        cur_state = env.reset()
        #cur_state = cur_state.reshape(1,len(cur_state))[0]
        cur_state = cur_state.reshape(len(cur_state),1).tolist()

        #tqdm.write('Warm-Up for {} Steps...'.format(num_warmup_steps))
        while warmup_counter < num_warmup_steps:
            action, epsilon            = Agent.act(cur_state)
            new_state, reward, done, step_counter_episode, _ = env.step(action, epsilon)
            new_state                  = new_state.reshape(len(cur_state),1).tolist()
            Agent.remember(cur_state, action, reward, new_state, done, step_counter_episode)

            cur_state                  = new_state
            warmup_counter            += 1

        bar = tqdm(range(epochs_len))#, leave=True, file=sys.stdout)
        bar.set_description("Training - Epoch {}".format(e))
        for step in bar:

            action, epsilon            = Agent.act(cur_state)
            new_state, reward, done, step_counter_episode, _ = env.step(action, epsilon)
            new_state                  = new_state.reshape(len(cur_state),1).tolist()            
            Agent.remember(cur_state, action, reward, new_state, done, step_counter_episode)
            
            cur_state                  = new_state
            
            if done == False:
                index_len = update_num
            else:
                index_len = update_num + R_HORIZON

            update_counter += 1
            if update_counter == update_num or done == True:
                Agent.replay(index_len)
                update_counter = 0

            if done:
                break
        #bar.clear()

        if e % 10 == 0:
            Agent.save_agent(NAME, DATENSATZ_PATH, e)


if __name__ == "__main__":
    main()





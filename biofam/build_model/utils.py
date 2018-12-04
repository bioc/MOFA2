from __future__ import division
from time import sleep
from time import time
import numpy as np
import scipy as s
import pandas as pd
import numpy.ma as ma
import os
import h5py

from biofam.core.nodes import *


def mask_data(data, mask_fraction):
    """ Method to mask data values, mainly used to evaluate imputation

    PARAMETERS
    ----------
    data: ndarray
    mask_fraction: float with the fraction of values to mask (from 0 to 1)
    """

    D = data.shape[1]
    N = data.shape[0]

    mask = np.ones(N*D)
    mask[:int(round(N*D*mask_fraction))] = np.nan
    s.random.shuffle(mask)
    mask = np.reshape(mask, [N, D])
    data *= mask

    return data

def _gaussianise_vec(vec):
    # take ranks and scale to uniform
    vec = s.stats.rankdata(vec, 'dense').astype(float)
    vec /= (vec.max()+1.)

    # transform uniform to gaussian using probit
    vec_norm = np.sqrt(2.) * s.special.erfinv(2.*vec-1.)  # TODO to double check
    # phenotype_norm = np.reshape(phenotype_norm, [len(phenotype_norm), 1])

    return vec_norm

def gaussianise(Y_m, axis=0):
    # double check axis for pandas
    Y_norm = Y_m.apply(_gaussianise_vec, axis)

    return Y_norm

def loadData(data_opts, verbose=True):
    """ Method to load the data

    PARAMETERS
    ----------
    data_opts: dic
    verbose: boolean
    """

    print ("\n")
    print ("#"*18)
    print ("## Loading data ##")
    print ("#"*18)
    print ("\n")

    uniq_views_names = np.unique(data_opts['views_names'])
    M = len(uniq_views_names)
    P = None if not ("groups_names" in  data_opts) else len(set(data_opts["groups_names"]))

    Y =  [None] * M
    samples_groups = None


    if P is None or P == 1:
        assert len(data_opts['input_files']) == len(uniq_views_names) == len(data_opts["views_names"]), "View names should be unique if there are no groups"
        for m, vname in enumerate(uniq_views_names):
            # Read files as views
            file = data_opts['input_files'][m]
            Y[m] = pd.read_csv(file, delimiter=data_opts["delimiter"], header=data_opts["colnames"], index_col=data_opts["rownames"]).astype(pd.np.float32)
            # if data_opts['features_in_rows']: Y[m] = Y[m].T
            group_name = data_opts["groups_names"][0] if "groups_names" in data_opts else 'group_0'
            samples_groups = list([group_name for e in range(Y[m].shape[0])])
            print("Loaded %s with dim (%d, %d)..." % (file, Y[m].shape[0], Y[m].shape[1]))
    else:  # there are multiple groups
        for m, vname in enumerate(uniq_views_names):
            uniq_groups_names = np.unique(data_opts["groups_names"])
            group_y = [None] * len(uniq_groups_names)
            indices = np.where(np.array(data_opts["views_names"]) == vname)[0]
            groups_names = [data_opts["groups_names"][e] for e in indices]
            assert len(groups_names) == len(uniq_groups_names), "Group names for one view should be unique"
            samples_groups = list()
            for j, i in enumerate(indices):
                file = data_opts["input_files"][i]
                group = data_opts["groups_names"][i]
                group_y[j] = pd.read_csv(file, delimiter=data_opts["delimiter"], header=data_opts["colnames"], index_col=data_opts["rownames"]).astype(pd.np.float32)
                # if data_opts['features_in_rows']: group_y[j] = group_y[j].T
                samples_groups.extend([group for e in range(group_y[j].shape[0])])
                print("Loaded %s with dim (%d, %d)..." % (file, group_y[j].shape[0], group_y[j].shape[1]))
            Y[m] = pd.concat(group_y)


    # Deprecated for 2d models
    # Check that the dimensions match
    # if len(set([Y[m].shape[0] for m in range(M)])) != 1:
    #     if len(set([Y[m].shape[1] for m in range(M)])) == 1:
    #         print("\nWarning: Columns seem to be the shared axis, transposing the data...")
    #         for m in range(M): Y[m] = Y[m].T
    #     else:
    #         print("\nError: Dimensionalities do not match, aborting. Data should be mapped to one dimension. Please make sure that data files have either rows or columns shared.")
    #         exit()

    # if data_opts['features_in_rows']:
    #     for m in range(M): Y[m] = Y[m].T
    #     if len(set([Y[m].shape[1] for m in range(M)])) == 1:
    #         print("\nWarning: Columns seem to be the shared axis, transposing the data...")
    #         for m in range(M): Y[m] = Y[m].T
    #     else:
    #         print("\nError: Dimensionalities do not match, aborting. Data should be mapped to one dimension. Please make sure that data files have either rows or columns shared.")
    #         exit()

    # Y = process_data(Y, data_opts, samples_groups)

    return (Y, samples_groups)

def process_data(data, data_opts, samples_groups):

    parsed_data = data

    if type(data_opts['mask_zeros']) == bool:
        data_opts['mask_zeros'] = [data_opts['mask_zeros']] * len(data)

    for m in range(len(data)):

        # Convert data to numpy array format
        if isinstance(parsed_data[m], pd.DataFrame):
            parsed_data[m] = parsed_data[m].values

        # Convert to float32
        # parsed_data[m] = parsed_data[m].astype(np.float32)

        # Convert data to numpy array format
        if isinstance(parsed_data[m], pd.DataFrame):
            parsed_data[m] = parsed_data[m].values

        # For some wierd reason, when using R and reticulate, missing values are stored as -2147483648
        parsed_data[m][parsed_data[m] == -2147483648] = np.nan

        # Removing features with no variance
        # var = parsed_data[m].std(axis=0)
        # if np.any(var==0.):
        #     print("Warning: %d features(s) have zero variance, removing them..." % (var==0.).sum())
        #     parsed_data[m].drop(parsed_data[m].columns[np.where(var==0.)], axis=1, inplace=True)

        # Mask values
        if data_opts["mask"][m] > 0:
            print("Masking %.1f%% of values in view '%s'..." % (data_opts["mask"][m]*100, data_opts["views_names"][m]))
            parsed_data[m] = mask_data(parsed_data[m], data_opts['mask'][m])

        if data_opts['mask_zeros'][m]:
            print('Masking zeros for view ', m)
            parsed_data[m][parsed_data[m] == 0] = np.nan

        # Centering and scaling is only appropriate for gaussian data
        if data_opts["likelihoods"][m] in ["gaussian", "zero_inflated"]:

            # mask zeros if zero infalted likelihood
            if data_opts["likelihoods"][m] is "zero_inflated":
                zeros_mask = parsed_data[m]==0
                parsed_data[m][zeros_mask] = np.nan

            # Center features
            if data_opts['center_features_per_group']:
                for gp_name in data_opts['groups_names']:
                    filt = [gp==gp_name for gp in samples_groups]
                    parsed_data[m][filt,:] -= np.nanmean(parsed_data[m][filt,:],axis=0)
            else:
                parsed_data[m] -= np.nanmean(parsed_data[m],axis=0)

            # Scale views to unit variance
            if data_opts['scale_views']:
                parsed_data[m] /= np.nanstd(parsed_data[m])

            # quantile normalise features
            # if data_opts['gaussianise_features'][m]:
            #     print("Gaussianising features for view " + str(m) + "...")
            #     parsed_data[m] = gaussianise(parsed_data[m])

            # Scale features to unit variance
            if data_opts['scale_features']:
                parsed_data[m] /= np.nanstd(parsed_data[m], axis=0)

            # reset zeros if zero infalted likelihood
            if data_opts["likelihoods"][m] is "zero_inflated":
                parsed_data[m][zeros_mask] = 0.

    return parsed_data

def loadDataGroups(data_opts):
    """
    method to load the labels of the samples when there are groups of samples
    """
    if data_opts['samples_groups_file'] is None:
        return None
    sample_labels = np.genfromtxt(data_opts['samples_groups_file'], dtype='str')
    return sample_labels

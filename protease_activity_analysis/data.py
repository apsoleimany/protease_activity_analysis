""" Collection of data loading and processing functions """
import numpy as np
import pandas as pd
import itertools
import os

from utils import get_output_dir

def load_syneos(data_path, id_path, sheet_names):
    """ Read a Syneos file from a path and extract data

    Args:
        data_path (str): path to the Syneos xlsx file
        id_path (str): path to the SampleType xlsx file
        sheet_names (list, str): sheets to read

    Returns:
        data_matrix (pandas.pivot_table)
    """

    # read syneos excel file
    usecols = [2,3,6,7,8] # HARDCODED

    sheet_data = pd.read_excel(data_path,
        sheet_names, header=1, usecols=usecols)

    df = None
    for key, data in sheet_data.items():
        if df is None:
            df = data
        else:
            df = df.append(data)

    # read SampleType file
    sample_to_type = pd.read_excel(id_path, header=0, index_col=0)
    sample_type = sample_to_type.reindex(df["Sample ID"])
    df['Sample Type'] = sample_type.values

    # account for dilution factors
    replace_inds = ~np.isnan(df['Area Ratio'])
    df.loc[replace_inds,'Ratio'] = df.loc[replace_inds,'Area Ratio']

    # create data_matrix n x m where m is the number of reporters
    data_matrix = pd.pivot_table(df,
        values='Ratio',
        index=['Sample Type', 'Sample ID'],
        columns='Compound')
    return data_matrix

def process_syneos_data(data_matrix, features_to_use, stock_id,
    sample_type_to_use=None, sample_ID_to_use=None, sample_ID_to_exclude=None, save_name=None):
    """ Process syneos data. Keep relevant features and mean-normalize

    Args:
        data_matrix (pandas.df): syneos MS data w/ sample ID and type
        features_to_use (list, str): reporters to include
        stock_id (str): Sample Type ID for stock to use for normalization
        sample_type_to_use (list, str): sample types to use
        sample_ID_to_use (str): contains (sub)string indicator of samples to
            include, e.g. "2B" or "2hr" to denote 2hr samples. default=None
        sample_ID_to_use (list, str): specific sample IDs to exclude

    Returns:
        norm_data_matrix (pandas.df)
    """

    def eliminate_zero_row(row):
        """Identifies whether a row has two or more features that are zero.

        Args:
            row: data frame rows of syneos data

        Returns:
            log: array of booleans indicating whether row has >= two features
                that are zero-valued (True == >= 2 zero-valued features)
        """
        num_zeros = sum([x==0 for x in row])
        log = (num_zeros >= 2)
        return log

    # only include the reporters that are actually part of the panel
    new_matrix = pd.DataFrame(data_matrix[features_to_use])

    # eliminate those samples that have two or more 0 values for the reporters
    zero_rows = np.array(new_matrix.apply(eliminate_zero_row, axis=1))
    filtered_matrix = new_matrix[~zero_rows]

    # normalize everything to stock
    stock = filtered_matrix.loc[('Stock',stock_id)].to_numpy()
    filtered_matrix = filtered_matrix / stock
    filtered_matrix = filtered_matrix.drop('Stock', level='Sample Type')

    # eliminate those samples that do not meet the sample type name criterion
    if sample_type_to_use != None:
        undo_multi = filtered_matrix.reset_index()
        filtered_matrix = undo_multi[undo_multi['Sample Type'].isin(sample_type_to_use)]
        filtered_matrix = filtered_matrix.set_index(['Sample Type', 'Sample ID'])

    # eliminate those samples that do not meet the sample ID name criterion
    if sample_ID_to_use != None:
        undo_multi = filtered_matrix.reset_index()
        filtered_matrix = undo_multi[undo_multi['Sample ID'].str.contains(
            sample_ID_to_use)]
        filtered_matrix = filtered_matrix.set_index(['Sample Type', 'Sample ID'])

    # eliminate those samples that are specified for exclusion
    if sample_ID_to_exclude != None:
        undo_multi = filtered_matrix.reset_index()
        filtered_matrix = undo_multi[~undo_multi['Sample ID'].isin(sample_ID_to_exclude)]
        filtered_matrix = filtered_matrix.set_index(['Sample Type', 'Sample ID'])

    out_dir = get_output_dir()
    filtered_matrix.to_csv(os.path.join(out_dir, f"{save_name}_filtered_matrix.csv"))
    
##    # mean scaling
##    mean_scaled = filtered_matrix.div(filtered_matrix.mean(axis=1),axis=0)
##    out_dir = get_output_dir()
##    mean_scaled.to_csv(os.path.join(out_dir, f"{save_name}_mean_scaled.csv"))
####    
##    return mean_scaled

    import scipy.stats as stats
    # across samples
    zscore = pd.DataFrame(stats.zscore(filtered_matrix, axis=0))
##
##    # across reporter
##    #zscore = pd.DataFrame(stats.zscore(filtered_matrix, axis=1))
##
    zscore.columns = filtered_matrix.columns
    zscore.index = filtered_matrix.index

    zscore.to_csv(os.path.join(out_dir, f"{save_name}_z_scored.csv"))

    return zscore


def make_multiclass_dataset(data_dir, file_list, classes_to_include):
    """ Creates a dataset for multiclass classification.

    Args:
        data_dir (str): path to the directory where pickle files are
        file_list (list, str): list of pickle file names as in data_dir
        classes_to_include (list, str): list of Sample Type labels to consider

    Returns:
        X (np array): matrix of size n x m of the data, where n is the number of
            samples and m is the number of features
        Y (np array): matrix of size n x k containing the classification labels
            for the samples in the dataset, where k is the number of classes
        data (pd dataframe): pandas data frame containing X, Y, Sample Type, and
            Sample Type ID
    """
    # read pickle files in file list and load the data
    matrices = []
    for f in file_list:
        path = os.path.join(data_dir, f)
        data = pd.read_pickle(path)
        matrices.append(data)
    data = pd.concat(matrices)

    # get Sample Type and copy for class labeling
    sample_type = data.index.get_level_values('Sample Type').to_numpy()
    class_labels = np.copy(sample_type)

    # eliminate the data that is not in the classes_to_include
    inds_to_keep = [i for i, val in enumerate(class_labels) if val in classes_to_include]
    class_labels = class_labels[inds_to_keep]

    # prepare the data and return
    data = data.reset_index()
    data = data.iloc[inds_to_keep, :]
    data['Class Labels'] = class_labels
    data = data.set_index(['Sample Type', 'Sample ID', 'Class Labels'])
    X = data.to_numpy()
    Y = data.index.get_level_values('Class Labels').to_numpy()

    return X, Y, data

def make_class_dataset(data_dir, file_list, pos_classes=None, pos_class=None,
    neg_classes=None, neg_class=None, multi_class=False):
    """ Creates a dataset for binary classification.

    Args:
        data_dir (str): path to the directory where pickle files are
        file_list (list, str): list of pickle file names as in data_dir
        pos_classes (list, str): list of Sample Type labels to be considered in
            the positive class
        pos_class (str): what to rename the positive class
        neg_classes (list, str): list of Sample Type labels to be considered in
            the negative class
        neg_class (str): what to rename the negative class

    Returns:
        X (np array): matrix of size n x m of the data, where n is the number of
            samples and m is the number of features
        Y (np array): matrix of size n x 1 containing the classification labels
            for the samples in the dataset, for binary classification problem
        data (pd dataframe): pandas data frame containing X, Y, Sample Type, and
            Sample Type ID
    """
    # read pickle files in file list and load the data
    matrices = []
    for f in file_list:
        path = os.path.join(data_dir, f)
        data = pd.read_pickle(path)
        matrices.append(data)
    data = pd.concat(matrices)

    # get Sample Type and copy for class labeling
    sample_type = data.index.get_level_values('Sample Type').to_numpy()
    class_labels = np.copy(sample_type)

    # convert positive classes if necessary
    if pos_classes != None:
        pos_inds = [i for i, val in enumerate(sample_type) if val in pos_classes]
        class_labels[pos_inds] = pos_class
    # convert negative classes if necessary
    if neg_classes != None:
        neg_inds = [i for i, val in enumerate(sample_type) if val in neg_classes]
        class_labels[neg_inds] = neg_class

    # eliminate the data that is not in the pos_class or the neg_class
    classes = [neg_class, pos_class]
    inds_to_keep = [i for i, val in enumerate(class_labels) if val in classes]
    class_labels = class_labels[inds_to_keep]

    # prepare the data and return
    data = data.reset_index()
    data = data.iloc[inds_to_keep, :]
    data['Class Labels'] = class_labels
    data = data.set_index(['Sample Type', 'Sample ID', 'Class Labels'])
    X = data.to_numpy()
    Y = data.index.get_level_values('Class Labels').to_numpy()

    return X, Y, data

def get_plex(data_path):
    """ Reads a csv file with N-plex reporter and name mapping.

    Args:
        data_path (str): path to the file
    Returns:
        plex (list str): the reporters (i.e., 1UR3_01, etc)
        renamed (list str): renamed reporter names (i.e., PP01, etc)
    """
    reporters = pd.read_csv(data_path, header=0)
    plex = reporters["Reporter"].tolist()
    renamed = reporters["Name"].tolist()

    return plex, renamed

def read_names_from_uniprot(data_path, sheet_names):
    """ Read a excel file with Uniprot data and extract all gene names

    Args:
        data_path (str): path to the uniprot xlsx file most be exported from
            Uniprot and contain a "Gene name column"
        sheet_names (list, str): sheets to read

    Returns:
        all_names (dict): key (sheet), value (list of names)
    """

    # Import excel file
    sheet_data = pd.read_excel(data_path, sheet_names, header=0)

    all_names = {}
    for sheet in sheet_names:
        data = sheet_data[sheet]
        # Create a new column with the nuber of names for each inhibitor
        data['n'] = data["Gene names"].apply(lambda x: x.split(" "))

        names = list(itertools.chain.from_iterable(data['n'].values))
        all_names[sheet] = names

    return all_names

import numpy as np
import os
import pandas as pd
import torch
import torch.utils.data as data

from pandas.io.pytables import HDFStore
from torch.utils.data import DataLoader

from better_nilm.format_utils import to_list
from better_nilm.str_utils import homogenize_string
from better_nilm.model.preprocessing import get_thresholds
from better_nilm.model.preprocessing import get_status

APPLIANCE_NAMES = {
    "freezer": "fridge",
    "fridgefreezer": "fridge",
    "washerdryer": "washingmachine"
}


def load_ukdale_datastore(path_h5):
    """
    Loads the UKDALE h5 file as a datastore.
    
    Parameters
    ----------
    path_h5 : str
        Path to the original UKDALE h5 file

    Returns
    -------
    datastore : pandas.HDFStore
    """
    assert os.path.isfile(path_h5), f"Input path does not lead to file:" \
                                    f"\n{path_h5}"
    assert path_h5.endswith('.h5'), "Path must lead to a h5 file.\n" \
                                    f"Input is {path_h5}"
    datastore = pd.HDFStore(path_h5)
    return datastore


def load_ukdale_meter(datastore, building=1, meter=1, period='1min',
                      cutoff=10000.):
    """
    Loads an UKDALE meter from the datastore, and resamples it to given period.
    
    Parameters
    ----------
    datastore : pandas.HDFStore
    building : int, default=1
        Building ID.
    meter : int, default=1
        Meter ID.
    period : str, default='1min'
        Sample period. Time between records.
    cutoff : float, default=10000.
        Maximum load. Any value higher than this is decreased to match this 
        value.

    Returns
    -------
    s : pandas.Series
    """
    assert type(datastore) is HDFStore, "datastore must be " \
                                        "pandas.io.pytables.HDFStore\n" \
                                        f"Input is {type(datastore)}"
    key = '/building{}/elec/meter{}'.format(building, meter)
    m = datastore[key]
    v = m.values.flatten()
    t = m.index
    s = pd.Series(v, index=t).clip(0., cutoff)
    s[s < 10.] = 0.
    s = s.resample('1s').ffill(limit=300).fillna(0.)
    s = s.resample(period).mean().tz_convert('UTC')
    return s


def ukdale_datastore_to_series(path_labels, datastore, house, label,
                               period='1min', cutoff=10000.,
                               verbose=True):
    """
    
    Parameters
    ----------
    path_labels : str
        Path to the directory that contains the csv of the meter labels.
    datastore : pandas.HDFStore
    house : int
        Building ID
    label : str
        Meter name
    period : str, default='1min'
    cutoff : float, default=10000.
    verbose : bool, default=True

    Returns
    -------
    s : pandas.Series
    """
    # Load the meter labels
    assert os.path.isdir(path_labels), "Input path is not a directory:" \
                                       f"\n{path_labels}"
    filename = f"{path_labels}/house_%1d/labels.dat" % house
    assert os.path.isfile(filename), f"Path not found:\n{filename}"

    if verbose:
        print(filename)

    labels = pd.read_csv(filename, delimiter=' ',
                         header=None, index_col=0).to_dict()[1]

    # Homogenize input label
    label = homogenize_string(label)
    label = APPLIANCE_NAMES.get(label, label)

    # Series placeholder
    s = None

    # Iterate through all the existing labels, searching for the input label
    for i in labels:
        lab = homogenize_string(labels[i])
        lab = APPLIANCE_NAMES.get(lab, lab)
        # When we find the input label, we load the meter records
        if lab == label:
            print(i, labels[i])
            s = load_ukdale_meter(datastore, house, i, period, cutoff)

    if s is None:
        raise ValueError(f"Label {label} not found on house {house}\n"
                         f"Valid labels are: {list(labels.values())}")

    s.index.name = 'datetime'
    s.name = label

    return s


def load_ukdale_series(path_h5, path_labels, buildings, list_appliances,
                       dates=None):
    """
    
    Parameters
    ----------
    path_h5 : str
        Path to the original UKDALE h5 file
    path_labels : str
        Path to the directory that contains the csv of the meter labels.
    buildings : list
        List of buildings IDs. List of integers.
    list_appliances : list
        List of appliances labels. List of strings.
    dates : dict, default=None
    {building_id : (date_start, date_end)}
    Both dates are strings with format: 'YY-MM-DD'

    Returns
    -------
    ds_meter : list
        List of dataframes.
    ds_appliance : list
        List of dataframes.
    ds_status : list
        List of dataframes.
    """
    # Load datastore
    datastore = load_ukdale_datastore(path_h5)

    # Ensure both parameters are lists
    buildings = to_list(buildings)
    list_appliances = to_list(list_appliances)
    list_appliances = list(set(list_appliances))
    # Make a list of meters
    list_meters = list_appliances.copy()
    list_meters.append('aggregate')

    # Initialize list
    ds_meter = []
    ds_appliance = []
    ds_status = []

    for house in buildings:
        meters = []
        for m in list_meters:
            meter = ukdale_datastore_to_series(path_labels, datastore, house,
                                               m, cutoff=10000.)
            meters += [meter]

        meters = pd.concat(meters, axis=1)
        meters.fillna(method='pad', inplace=True)

        # Pick range of dates
        if (type(dates) == dict) and (house in dates.keys()):
            date_start = dates[house][0]
            date_start = pd.to_datetime(date_start).tz_localize('US/Eastern')
            date_end = dates[house][1]
            date_end = pd.to_datetime(date_end).tz_localize('US/Eastern')
            meters = meters[date_start:date_end]

        meter = meters['aggregate']
        appliances = meters.drop('aggregate', axis=1)

        arr_apps = np.expand_dims(appliances.values, axis=1)
        thresholds = get_thresholds(arr_apps)
        assert len(thresholds) == len(
            list_appliances), "Number of thresholds doesn't match number of " \
                              "appliances "
        status = get_status(arr_apps, thresholds)
        status = status.reshape(status.shape[0], len(list_appliances))
        status = pd.DataFrame(status, columns=list_appliances,
                              index=appliances.index)

        ds_meter.append(meter)
        ds_appliance.append(appliances)
        ds_status.append(status)

    return ds_meter, ds_appliance, ds_status


class Power(data.Dataset):
    def __init__(self, meter=None, appliance=None, status=None,
                 length=256, border=680, max_power=1., train=False):
        self.length = length
        self.border = border
        self.max_power = max_power
        self.train = train

        self.meter = meter.copy() / self.max_power
        self.appliance = appliance.copy() / self.max_power
        self.status = status.copy()

        self.epochs = (len(self.meter) - 2 * self.border) // self.length

    def __getitem__(self, index):
        i = index * self.length + self.border
        if self.train:
            i = np.random.randint(self.border,
                                  len(self.meter) - self.length - self.border)

        x = self.meter.iloc[
            i - self.border:i + self.length + self.border].values.astype(
            'float32')
        y = self.appliance.iloc[i:i + self.length].values.astype('float32')
        s = self.status.iloc[i:i + self.length].values.astype('float32')
        x -= x.mean()

        return x, y, s

    def __len__(self):
        return self.epochs


def _train_valid_test(ds_meter, ds_appliance, ds_status, num_buildings,
                      train_size=0.8, valid_size=0.1,
                      seq_len=512, border=16, max_power=10000.):
    """
    Splits data store data into train, validation and test.
    Parameters
    ----------
    ds_meter
    ds_appliance
    ds_status
    num_buildings
    train_size
    valid_size
    seq_len
    border
    max_power

    Returns
    -------
    ds_train
    ds_valid
    ds_test
    """
    ds_len = [len(ds_meter[i]) for i in range(num_buildings)]

    ds_train = [Power(ds_meter[i][:int(train_size * ds_len[i])],
                      ds_appliance[i][:int(train_size * ds_len[i])],
                      ds_status[i][:int(train_size * ds_len[i])],
                      seq_len, border, max_power, True) for i in
                range(num_buildings)]

    ds_valid = [
        Power(ds_meter[i][int(train_size * ds_len[i]):int(
            (train_size + valid_size) * ds_len[i])],
              ds_appliance[i][int(train_size * ds_len[i]):int(
                  (train_size + valid_size) * ds_len[i])],
              ds_status[i][int(train_size * ds_len[i]):int(
                  (train_size + valid_size) * ds_len[i])],
              seq_len, border, max_power, False) for i in range(num_buildings)]

    ds_test = [
        Power(ds_meter[i][int((train_size + valid_size) * ds_len[i]):],
              ds_appliance[i][int((train_size + valid_size) * ds_len[i]):],
              ds_status[i][int((train_size + valid_size) * ds_len[i]):],
              seq_len, border, max_power, False) for i in
        range(num_buildings)]
    return ds_train, ds_valid, ds_test


def _datastore_to_dataloader(ds, buildings, batch_size, shuffle):
    """
    Turns a datastore into a dataloader.
    
    Parameters
    ----------
    ds
    buildings
    batch_size
    shuffle

    Returns
    -------
    dl
    """
    buildings = to_list(buildings)
    ds = []
    for building in buildings:
        ds += [ds[building]]
    ds = torch.utils.data.ConcatDataset(ds)
    dl = DataLoader(dataset=ds, batch_size=batch_size, shuffle=shuffle)
    return dl


def datastores_to_dataloaders(ds_meter, ds_appliance, ds_status, num_buildings,
                              build_id_train, build_id_valid, build_id_test,
                              train_size=0.8, valid_size=0.1, batch_size=64,
                              seq_len=512, border=16, max_power=10000.):
    """
    Turns datastores into dataloaders.
    
    Parameters
    ----------
    ds_meter
    ds_appliance
    ds_status
    num_buildings
    build_id_train
    build_id_valid
    build_id_test
    train_size
    valid_size
    batch_size
    seq_len
    border
    max_power

    Returns
    -------
    dl_train
    dl_valid
    dl_test

    """
    ds_train, \
    ds_valid, \
    ds_test = _train_valid_test(
        ds_meter, ds_appliance, ds_status, num_buildings,
        train_size=train_size, valid_size=valid_size,
        seq_len=seq_len, border=border, max_power=max_power)

    dl_train = _datastore_to_dataloader(ds_train, build_id_train,
                                        batch_size, True)
    dl_valid = _datastore_to_dataloader(ds_valid, build_id_valid,
                                        batch_size, False)
    dl_test = _datastore_to_dataloader(ds_test, build_id_test,
                                       batch_size, False)
    return dl_train, dl_valid, dl_test


def _buildings_to_idx(buildings, build_id_train, build_id_valid,
                      build_id_test):
    """
    Takes the list of buildings ID and changes them to their corresponding 
    index.
    
    Parameters
    ----------
    buildings
    build_id_train
    build_id_valid
    build_id_test

    Returns
    -------
    build_idx_train
    build_idx_valid
    build_idx_test

    """
    # Train, valid and test buildings must contain the index, not the ID of
    # the building. Change that
    if build_id_train is None:
        build_idx_train = [i for i in range(len(buildings))]
    else:
        build_idx_train = []

    if build_id_valid is None:
        build_idx_valid = [i for i in range(len(buildings))]
    else:
        build_idx_valid = []

    if build_id_test is None:
        build_idx_test = [i for i in range(len(buildings))]
    else:
        build_idx_test = []

    for idx, building in enumerate(buildings):
        if (build_id_train is not None) and (building in build_id_train):
            build_idx_train += [idx]
        if (build_id_valid is not None) and (building in build_id_valid):
            build_idx_valid += [idx]
        if (build_id_test is not None) and (building in build_id_test):
            build_idx_test += [idx]

    assert len(build_idx_train) > 0, f"No ID in build_id_train matches the " \
                                     f"ones of buildings."
    assert len(build_idx_valid) > 0, f"No ID in build_id_valid matches the " \
                                     f"ones of buildings."
    assert len(build_idx_test) > 0, f"No ID in build_id_test matches the " \
                                    f"ones of buildings."

    return build_idx_train, build_idx_valid, build_idx_test


def load_dataloaders(path_h5, path_data, buildings, appliances,
                     dates=None,
                     build_id_train=None, build_id_valid=None,
                     build_id_test=None,
                     train_size=0.8, valid_size=0.1, batch_size=64,
                     seq_len=512, border=16, max_power=10000.):
    """
    Load the UKDALE dataloaders from the raw data.
    
    Parameters
    ----------
    path_h5
    path_data
    buildings
    appliances
    dates
    build_id_train
    build_id_valid
    build_id_test
    train_size
    valid_size
    batch_size
    seq_len
    border
    max_power

    Returns
    -------
    dl_train
    dl_valid
    dl_test

    """
    build_idx_train, \
    build_idx_valid, \
    build_idx_test = _buildings_to_idx(buildings, build_id_train,
                                       build_id_valid, build_id_test)

    # Load the different datastores
    ds_meter, ds_appliance, ds_status = load_ukdale_series(path_h5, path_data,
                                                           buildings,
                                                           appliances,
                                                           dates=dates)
    num_buildings = len(buildings)

    # Load the data loaders
    dl_train, \
    dl_valid, \
    dl_test = datastores_to_dataloaders(ds_meter, ds_appliance, ds_status,
                                        num_buildings, build_idx_train,
                                        build_idx_valid, build_idx_test,
                                        train_size=train_size,
                                        valid_size=valid_size,
                                        batch_size=batch_size,
                                        seq_len=seq_len, border=border,
                                        max_power=max_power)
    return dl_train, dl_valid, dl_test

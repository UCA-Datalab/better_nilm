import logging
import os
import random

import numpy as np
import pandas as pd
import torch.utils.data as data
from torch.utils.data import DataLoader

from nilm_thresholding.data.threshold import Threshold

logging.basicConfig(level=logging.DEBUG, format="%(message)s")


class DataSet(data.Dataset):
    files: list = list()
    epochs: int = 0
    appliances: list = list()
    status: list = list()

    def __init__(
        self,
        path_data: str,
        subset: str = "train",
        power_scale: int = 2000,
        input_len: int = 510,
        border: int = 15,
        buildings: dict = None,
        train_size: float = 0.8,
        valid_size: float = 0.1,
        shuffle: bool = False,
        random_seed: int = 0,
        threshold: dict = None,
        **kwargs,
    ):
        self.subset = subset
        self.power_scale = power_scale
        self.border = border
        self.length = input_len
        self.buildings = {} if buildings is None else buildings[subset]
        self.train_size = train_size
        self.validation_size = valid_size
        self.shuffle = shuffle
        self.random_seed = random_seed
        self._list_files(path_data)
        self._get_parameters_from_file()

        # Set the parameters according to given threshold method
        param_thresh = {} if threshold is None else threshold
        self.threshold = Threshold(appliances=self.appliances, **param_thresh)

        logging.debug(
            f"Received extra kwargs, not used:\n   {', '.join(kwargs.keys())}"
        )

    @staticmethod
    def _open_file(path_file: str) -> pd.DataFrame:
        """Opens a csv as a pandas.DataFrame"""
        df = pd.read_csv(path_file, index_col=0)
        return df

    def _list_files(self, path_data: str):
        """List the files pertaining to given subset"""
        # Initialize empty file list
        files = []
        # Loop through the datasets and buildings as sorted in config
        for dataset, buildings in self.buildings.items():
            for building in buildings:
                path_building = os.path.join(path_data, f"{dataset}_{building}")
                files_of_building = sorted(
                    [
                        os.path.join(path_building, file)
                        for file in os.listdir(path_building)
                    ]
                )
                val_idx = int(len(files_of_building) * self.train_size)
                test_idx = val_idx + int(len(files_of_building) * self.validation_size)
                # Shuffle if requested
                if self.shuffle:
                    random.seed(self.random_seed)
                    random.shuffle(files_of_building)
                # Pick subset to choose from
                if self.subset == "train":
                    files += files_of_building[:val_idx]
                elif self.subset == "validation":
                    files += files_of_building[val_idx:test_idx]
                elif self.subset == "test":
                    files += files_of_building[test_idx:]
        # Update the class parameters
        self.files = files
        self.epochs = len(files)
        logging.info(f"{self.epochs} data points found for {self.subset}")

    def _get_parameters_from_file(self):
        """Updates class parameters from sample csv file"""
        df = self._open_file(self.files[0])
        appliances = [t for t in df.columns if not t.endswith("_status")]
        appliances.remove("aggregate")
        self.appliances = sorted(appliances)
        self.status = [t + "_status" for t in appliances]
        self.length = df.shape[0]
        self._idx_start = self.border
        self._idx_end = self.length - self.border

    def _compute_status(self, arr_apps: np.array) -> np.array:
        status = self.threshold.get_status(arr_apps)
        status = status.reshape(status.shape[0], len(self.appliances))
        return status

    def __getitem__(self, index):
        path_file = self.files[index]
        df = self._open_file(path_file)
        x = df["aggregate"].values / self.power_scale
        y = (
            df[self.appliances].iloc[self._idx_start : self._idx_end].values
            / self.power_scale
        )
        s = self._compute_status(y)
        return x, y, s

    def __len__(self):
        return self.epochs


def return_dataloader(
    path_data: str,
    config: dict,
    subset: str = "train",
    shuffle: bool = True,
):
    dataset = DataSet(path_data, subset=subset, **config)
    dataloader = DataLoader(
        dataset=dataset, batch_size=config["batch_size"], shuffle=shuffle
    )
    logging.debug(f"\nDataloader ready for {subset}!")
    return dataloader

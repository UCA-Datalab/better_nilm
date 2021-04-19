import os

import pandas as pd
import torch.utils.data as data
from torch.utils.data import DataLoader


class DataSet(data.Dataset):
    appliances: list = list()
    status: list = list()
    length: int = 510

    def __init__(
        self,
        path_data: str,
        buildings: dict = None,
        power_scale: float = 2000,
        border: int = 15,
    ):
        self.power_scale = power_scale
        self.border = border

        folders = [k + "_" + str(i) for k, v in buildings.items() for i in v]
        folders = [
            os.path.join(path_data, f) for f in folders if f in os.listdir(path_data)
        ]
        self.files = [os.path.join(f, x) for f in folders for x in os.listdir(f)]
        self.epochs = len(self.files)

        self._get_parameters_from_file()

    @staticmethod
    def _open_file(path_file: str) -> pd.DataFrame:
        df = pd.read_csv(path_file, index_col=0)
        return df

    def _get_parameters_from_file(self):
        df = self._open_file(self.files[0])
        appliances = [t for t in df.columns if not t.endswith("_status")]
        appliances.remove("aggregate")
        self.appliances = appliances
        self.status = [t + "_status" for t in appliances]
        self.length = df.shape[0]
        self._idx_start = self.border - 1
        self._idx_end = self.length - self.border + 1

    def __getitem__(self, index):
        path_file = self.files[index]
        df = self._open_file(path_file)
        x = df["aggregate"].values / self.power_scale
        y = (
            df[self.appliances].iloc[self._idx_start : self._idx_end].values
            / self.power_scale
        )
        s = df[self.status].iloc[self._idx_start : self._idx_end].values
        return x, y, s

    def __len__(self):
        return self.epochs


def return_dataloader(
    path_data: str,
    config_data: dict,
    config_model: dict,
    shuffle: bool = True,
):
    dataset = DataSet(
        path_data,
        buildings=config_data["train"]["buildings"],
        power_scale=config_data["power_scale"],
        border=config_model["border"],
    )
    dataloader = DataLoader(
        dataset=dataset, batch_size=config_model["batch_size"], shuffle=shuffle
    )
    return dataloader
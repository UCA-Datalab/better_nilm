import os
import pandas as pd
import sys

sys.path.insert(0, "../better_nilm")

from better_nilm.nilmtk.data_loader import buildings_to_array

from better_nilm.model.preprocessing import preprocessing_pipeline_dict
from better_nilm.model.preprocessing import normalize_meters
from better_nilm.model.preprocessing import denormalize_meters
from better_nilm.model.preprocessing import feature_target_split
from better_nilm.model.preprocessing import get_thresholds
from better_nilm.model.preprocessing import get_status

from better_nilm.model.architecture.gru import create_gru_model
from better_nilm.model.train import train_with_validation

from better_nilm.model.export import store_model_json
from better_nilm.model.export import store_dict_pkl

from better_nilm.model.scores import regression_score_dict
from better_nilm.model.scores import classification_scores_dict

"""
This script is designed to train models in only one house and one appliance,
then test that model against all the other houses that have the appliance.
"""

appliances = ['dishwasher',
              'fridge',
              'microwave',
              'television']
dict_path_buildings = {
    "../nilm/data/nilmtk/redd.h5": [1, 2, 3, 4, 5, 6],
    "../nilm/data/nilmtk/ukdale.h5": [2, 3, 4, 5]}
path_output = "outputs/"

sample_period = 6
series_len = 600
num_series = 80
skip_first = None
to_int = True

train_size = .6
validation_size = .2
epochs = 1000
batch_size = 64
patience = 100

# Weights
class_w = 1
reg_w = 1

"""
Begin script
"""

if not os.path.isdir(path_output):
    os.mkdir(path_output)

test_size = 1 - train_size - validation_size
num_test = int(series_len * test_size)

# Turn dictionary into list
buildings = []
for path, ls in dict_path_buildings.items():
    for build in ls:
        buildings += [(path, build)]

for app in appliances:
    for tuple_ in buildings:

        # Building name
        dataset = tuple_[0].rsplit("/", 1)[1]
        dataset = dataset.rsplit(".", 1)[0]
        building_name = dataset + str(tuple_[1])
        file_name = app + "_" + building_name

        print("\n----------------------------------------------------------\n")
        print(f"Appliance: {app}\nBuilding: {building_name}\n")

        dict_path_building = {tuple_[0]: tuple_[1]}

        """
        Load the data
        """

        try:
            ser, meters = buildings_to_array(dict_path_building,
                                             appliances=app,
                                             sample_period=sample_period,
                                             series_len=series_len,
                                             max_series=num_series,
                                             skip_first=skip_first,
                                             to_int=to_int)
        except ValueError:
            # If the appliance is not in the building, skip it
            print("Appliance not found in building.\nSkipped.\n")
            continue

        if ser.shape[0] != num_series:
            print(f"WARNING\nDesired number of series is {num_series}\n"
                  f"but the amount retrieved is {ser.shape[0]}")

        if ser.shape[1] != series_len:
            raise ValueError(f"Series length must be {series_len}\n"
                             f"Retrieved length is {ser.shape[1]}")

        """
        Preprocessing
        """

        dict_prepro = preprocessing_pipeline_dict(ser, meters,
                                                  train_size=train_size,
                                                  validation_size=
                                                  validation_size)

        x_train = dict_prepro["train"]["x"]
        y_train = dict_prepro["train"]["y"]
        bin_train = dict_prepro["train"]["bin"]

        x_val = dict_prepro["validation"]["x"]
        y_val = dict_prepro["validation"]["y"]
        bin_val = dict_prepro["validation"]["bin"]

        x_test = dict_prepro["test"]["x"]
        y_test = dict_prepro["test"]["y"]
        bin_test = dict_prepro["test"]["bin"]

        x_max = dict_prepro["max_values"]["x"]
        y_max = dict_prepro["max_values"]["y"]

        appliances = dict_prepro["appliances"]
        num_appliances = dict_prepro["num_appliances"]
        thresholds = dict_prepro["thresholds"]

        """
        Training
        """

        model = create_gru_model(series_len, num_appliances, thresholds,
                                 classification_weight=class_w,
                                 regression_weight=reg_w)

        model = train_with_validation(model, x_train, [y_train, bin_train],
                                      x_val, [y_val, bin_val],
                                      epochs=epochs, batch_size=batch_size,
                                      patience=patience)

        """
        Store
        """
        path_model = os.path.join(path_output, file_name + ".json")
        store_model_json(model, path_model)

        path_dic = os.path.join(path_output, file_name + ".pkl")
        store_dict_pkl(dict_prepro["max_values"], path_dic)

        """
        Score
        """
        [y_pred, bin_pred] = model.predict(x_test)
        y_pred = denormalize_meters(y_pred, y_max)

        y_test = denormalize_meters(y_test, y_max)

        reg_scores = regression_score_dict(y_pred, y_test, appliances)
        class_scores = classification_scores_dict(bin_pred, bin_test,
                                                  appliances)

        # Initialize scores dictionary
        scores = {building_name: {**reg_scores[app], **class_scores[app]}}

        """
        Test
        """
        for tuple_2 in buildings:
            # Ignore the building with which we trained
            if tuple_ == tuple_2:
                continue

            dict_path_building = {tuple_2[0]: tuple_2[1]}

            try:
                ser, meters = buildings_to_array(dict_path_building,
                                                 appliances=app,
                                                 sample_period=sample_period,
                                                 series_len=series_len,
                                                 max_series=num_test,
                                                 skip_first=skip_first,
                                                 to_int=to_int)
            except ValueError:
                # If the app is not in the building, skip it
                continue

            # Split data into X and Y
            x_test, y_test = feature_target_split(ser, meters)

            # Normalize
            x_test, _ = normalize_meters(x_test, max_values=x_max)

            # Get the binary meter status of each Y series
            thresholds = get_thresholds(y_test)
            bin_test = get_status(y_test, thresholds)

            # Propagate X data through the model to get the predictions
            [y_pred, bin_pred] = model.predict(x_test)
            y_pred = denormalize_meters(y_pred, y_max)

            reg_scores = regression_score_dict(y_pred, y_test, appliances)
            class_scores = classification_scores_dict(bin_pred, bin_test,
                                                      appliances)

            # Building name
            dataset = tuple_2[0].rsplit("/", 1)[1]
            dataset = dataset.rsplit(".", 1)[0]
            building_name = dataset + str(tuple_2[1])

            # Add to scores dictionary
            scores[building_name] = {**reg_scores[app], **class_scores[app]}

        # Create dataframe from dictionary
        df = pd.DataFrame.from_dict(scores)
        path_df = os.path.join(path_output, file_name + ".csv")
        df.to_csv(path_df)

        print("Done.\n")
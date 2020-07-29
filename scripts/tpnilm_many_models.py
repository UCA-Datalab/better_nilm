import os
import sys

path_main = os.path.realpath(__file__)
path_main = path_main.rsplit('/', 2)[0]
sys.path.insert(0, path_main)

"""
Trains several TP-NILM models under the same conditions
"""

# Parameters to modify

path_h5 = os.path.join(path_main, 'data/ukdale.h5')
path_data = os.path.join(path_main, '../nilm/data/ukdale')

build_id_train = [1, 2, 5]
build_id_valid = [1]
build_id_test = [1]
appliances = ['fridge', 'dish_washer', 'washing_machine']

class_w = 1
reg_w = 0

dates = {1: ('2013-04-12', '2014-12-15'),
         2: ('2013-05-22', '2013-10-03 6:16'),
         5: ('2014-04-29', '2014-09-01')}

train_size = 0.8
valid_size = 0.1

output_len = 480
border = 16
period = '1min'
power_scale = 2000.

batch_size = 32
learning_rate = 1.E-4
dropout = 0.1
epochs = 300
patience = 300

num_models = 10

# Other parameters (no need to modify these)

buildings = sorted(set(build_id_train + build_id_valid + build_id_test))
num_appliances = len(appliances)

# Model

model_name = 'TPNILMModel'
model_params = {'output_len': output_len,
                # 'border': border,
                'out_channels': num_appliances,
                'init_features': 32,
                'learning_rate': learning_rate,
                'dropout': dropout,
                'classification_w': class_w,
                'regression_w': reg_w}


# Run main script

print("TP-NILM many models\n")

sys.path.insert(0, path_main)

from better_nilm._script._script_many_models import run_many_models

for threshold_method in ['vs', 'at', 'mp']:
    run_many_models(path_h5=path_h5, path_data=path_data, path_main=path_main,
                    buildings=buildings, build_id_train=build_id_train,
                    build_id_valid=build_id_valid,
                    build_id_test=build_id_test, appliances=appliances,
                    class_w=class_w, reg_w=reg_w, dates=dates,
                    train_size=train_size, valid_size=valid_size,
                    output_len=output_len, border=border, period=period,
                    power_scale=power_scale,
                    batch_size=batch_size, learning_rate=learning_rate,
                    dropout=dropout,
                    epochs=epochs, patience=patience, num_models=num_models,
                    model_name=model_name, model_params=model_params,
                    threshold_method=threshold_method)

import sys

sys.path.insert(0, "../better_nilm")

from better_nilm.nilmtk.data_loader import buildings_to_array

dict_path_buildings = {
    "../nilm/data/nilmtk/redd.h5": [1, 2],
    "../nilm/data/nilmtk/ukdale.h5": 5}

appliances = None
sample_period = 6
series_len = 600
max_series = None
to_int = True

output = buildings_to_array(dict_path_buildings,
                            appliances=appliances,
                            sample_period=sample_period,
                            series_len=series_len,
                            max_series=max_series,
                            to_int=to_int)

print(output)

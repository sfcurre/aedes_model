import tensorflow as tf
import tensorflow.keras.backend as K
import os, json
import pandas as pd, numpy as np
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import r2_score
from itertools import chain
import models.models
from glob import glob
from scipy.signal import savgol_filter

"""
Function: r2_keras        
----------
Use: Loss function for neural networks. Used to load .h5 files
"""
def r2_keras(y_true, y_pred):
    SS_res =  K.sum(K.square(y_true - y_pred))
    SS_tot = K.sum(K.square(y_true - K.mean(y_true))) 
    return (1 - SS_res/(SS_tot + K.epsilon()))


"""
Function: smooth        
----------
Use: Apply Savitzy Golay filter 
"""
def smooth(nn):
    nn=nn.astype(float)
    # threshold is hardcoded 11 day auto correlation of MoLS
    threshold=0.925
    nn=savgol_filter(nn,11,3)
    it=0
    while (pd.Series(nn).autocorr(11) < threshold-0.01) and (it<50):
        nn=savgol_filter(nn,11,3)
        it+=1
    nn[nn<0]=0
    return nn


"""
Function: format_data        
----------
Use: Function scales input data between [0, 1] and formats into 90-day samples.

Parameters:
  data: a dataframe of daily weather data with columns:
          Counties, Year, Month, Day, Precipitation, Max Temp, Min Temp,
          Humidity, MoLS (replace with 0 if no MoLS data available)
          Data is a .pd file.
  data_shape: shape of one training sample for the model (90x4)

  scaler: MinMaxScaler to scale data to [0,1] and based off of training data.
             Pass previously calculated scaler. Default: None.

  fit_scaler: Boolean argument. If True, function will calculate MinMaxScaler
                 for given data data. Default: False

Returns:
  If fit_scaler = False,
      returns (scaled input data, spatiotemporal information)
  If fit_scaler = True,
      returns (scaled input data, spatiotemporal information, scaler fit to data) 
"""
def format_data(data, data_shape, scaler = None, fit_scaler = False):
    data.columns = range(0, len(data.columns))
    if fit_scaler:
        scaler=MinMaxScaler()
        scaler.fit(data.iloc[:, -(data_shape[1] + 1):])
    groups = data.groupby(by = 0)
    X, counties = list(), list()
    for _, subset in groups:
        for i in range(len(subset)):
            if (i+data_shape[0])<len(subset):
                X.append(scaler.transform(subset.iloc[i: i + data_shape[0], -(data_shape[1] + 1):].values))
                counties.append(subset.iloc[i+data_shape[0],0:4])
    return (np.array(X),np.array(counties)) if not fit_scaler else (np.array(X),np.array(counties), scaler)

"""
Function: generate_predictions        
----------
Use: Function uses parameter scaler (MinMaxScaler) to transform input data
      in samples of size data_shape, or calculates scaler off of given data.
      Predictions for gravid female mosquitoes are generated using the neural network in
      parameter model.

Input Parameters:
  model: a saved neural network model used for the prediction generation.
          Model is a .h5 file.

  data: a dataframe of daily weather data with columns:
          Counties, Year, Month, Day, Precipitation, Max Temp, Min Temp,
          Humidity, MoLS (replace with 0 if no MoLS data available)
          Data is a .pd file.
          
  data_shape: shape of one training sample for the model (90x4)

  mols: boolean set to False if predictions should be generated without MoLS data

  scaler: MinMaxScaler to scale data to [0,1] and based off of training data.
             Pass previously calculated scaler, otherwise keep default: None.

  fit_scaler: Boolean argument. If True, function will calculate MinMaxScaler
                 for given data data. Default: False

Returns:
  results: Array with the following columns: County, Year, Month, Day,
            MoLS prediction for spatiotemporal location, Model prediction for spatiotemporal location
           (Opt): MinMaxScaler() scaler if fit_scaler=True
"""
def generate_predictions(model, data, data_shape, scaler=None, fit_scaler=False):
    # Scale data to [0,1] and reformat to 90-day samples
    if fit_scaler==True:
        X,counties, scaler = format_data(data, data_shape, None, fit_scaler)
    else:
        X,counties = format_data(data, data_shape, scaler, fit_scaler)

    unique_counties=np.unique(counties[:,0])
    results=list()
    # Generate model predictions by county
    for i in range(len(unique_counties)):#county in unique_counties:
        county=unique_counties[i]
        print(county)
        loc=np.argwhere(counties[:,0]==county)[:,0]
        X_co, co= X[loc,:,:], counties[loc,:]
        model_preds=np.asarray(model.predict_on_batch(tf.convert_to_tensor(X_co[:,:,0:-1])))

        # Scale to original value range and concatenate results
        data_preds=np.zeros([len(X_co), data_shape[0], data_shape[1]+1])
        data_orig=np.zeros([len(X_co), data_shape[0], data_shape[1]+1])
        for i in range(len(X_co)):
            data_preds[i,:,:]=scaler.inverse_transform(np.concatenate([X_co[i,:,0:-1],model_preds[i,0]*np.ones((data_shape[0],1))], axis=1))
            data_orig[i,:,:]=scaler.inverse_transform(X_co[i,:,:])
        data_preds[:,-1,-1]=smooth(data_preds[:,-1,-1])
        results.append(np.concatenate([co[:,:],np.reshape(data_orig[:,-1,-1],(len(data_orig),1)),
                           np.reshape(data_preds[:,-1,-1],(len(data_preds),1))], axis=1))

    results=np.asarray(list(chain(*results)))        
    return results if not fit_scaler else (results,scaler)


def main():
    config="models/Configs/gru_config.json"
    model_files=glob("SavedModels/*")
    
    data_files=['DataFrames/train_data.pd','DataFrames/val_data.pd','DataFrames/test_data.pd']

    with open(config) as fp:
        config = json.load(fp)
    data_shape=config["data"]["data_shape"]

    for data_file in data_files:
        data=pd.read_pickle(data_file)
        if "train" in data_file:
            istrain=1
            marker_name="Train"
        elif "test" in data_file:
            is_train=0
            marker_name="Test"
        else:
            is_train=0
            marker_name="Val"
        for model_file in model_files:
            to_save=list()
            if os.path.exists(model_file):
                model = tf.keras.models.load_model(model_file, custom_objects={"r2_keras":r2_keras})
                if istrain==1:
                    results,scaler=generate_predictions(model, data, data_shape, None, fit_scaler=True)
                else:
                    results = generate_predictions(model, data, data_shape, scaler, fit_scaler=False)
                print(str(data_file.split('/')[-1]) + " " + str(model_file.split('/')[-1]))
                print(r2_score(results[:,-2], results[:,-1]))
                marker = list()
                model_name=model_file.split('/')[-1].split('.')[0]
                for i in range(len(results)):
                    marker.append(model_name)
                marker=np.asarray(marker)
                to_save.append(np.concatenate([np.reshape(marker, (len(marker),1)), results],axis=1))
            to_save=np.asarray(list(chain(*to_save)))
            to_save=pd.DataFrame(to_save, columns=['Model','County','Year',
                                               'Month','Day','MoLS','Neural Network'])
            to_save.to_csv("Raw_Predictions/"+marker_name+"_"+model_name+"_predictions.csv",index=False)

  
main()


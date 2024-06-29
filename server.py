from flask import Flask, request, jsonify
import csv
import os
from Parser import Parser
import navpy
import numpy as np
import warnings

# Suppress all warnings
warnings.filterwarnings("ignore")
app = Flask(__name__)

data_directory = os.path.join(os.getcwd(), 'data')
if not os.path.exists(data_directory):
    os.makedirs(data_directory)

data_file = os.path.join(data_directory, 'gnss_data.csv')
fields = ['svid', 'codeType', 'timeNanos', 'biasNanos', 'constellationType', 'svid', 
          'accumulatedDeltaRangeState', 'receivedSvTimeNanos', 'pseudorangeRateUncertaintyMetersPerSecond', 
          'accumulatedDeltaRangeMeters', 'accumulatedDeltaRangeUncertaintyMeters', 'carrierFrequencyHz', 
          'receivedSvTimeUncertaintyNanos', 'cn0DbHz', 'fullBiasNanos', 'multipathIndicator', 'timeOffsetNanos', 'state', 'pseudorangeRateMetersPerSecond']

# Global variables to store the latest data
latest_measurement = None
latest_position = None

@app.route('/latest_data', methods=['GET'])
def latest_data():
    return jsonify({
        "measurement": latest_measurement,
        "position": latest_position
    })

@app.route('/gnssdata', methods=['POST'])
def receive_gnss_data():
    global latest_measurement, latest_position
    measurements = request.get_json()
    print("Received GNSS measurements:", measurements)
    
    if not measurements:
        return jsonify({"status": "failure", "error": "No measurements received"}), 400
    
    # Update the latest measurement
    latest_measurement = measurements[-1] if measurements else None

    # Save the data to a CSV file
    with open(data_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fields)
        writer.writeheader()
        for measurement in measurements:
            filtered_measurement = {key: measurement.get(key, None) for key in fields}
            writer.writerow(filtered_measurement)
    
    # Process the data with the parser
    parser = Parser(data_directory)  # Initialize Parser with ephemeris data directory
    measurements = parser.open_file(data_file)
    measurements = parser.formatDF(measurements)
    
    if measurements.empty:
        return jsonify({"status": "failure", "error": "No valid measurements after formatting"}), 400
    
    one_epoch, ephemeris = parser.generate_epoch(measurements)
    
    if one_epoch.empty or ephemeris.empty:
        return jsonify({"status": "failure", "error": "No valid epoch or ephemeris data"}), 400
    
    sv_position = parser.calculate_satellite_position(ephemeris, one_epoch['transmit_time_seconds'])
    
    if sv_position.empty:
        return jsonify({"status": "failure", "error": "No valid satellite position data"}), 400
    
    sv_position["pseudorange"] = one_epoch["Pseudorange_Measurement"] + parser.LIGHTSPEED * sv_position['Sat.bias']
    sv_position["cn0"] = one_epoch["Cn0DbHz"]
    sv_position = sv_position.drop('Sat.bias', axis=1)
    sv_position.to_csv(os.path.join(data_directory, 'output_xyz.csv'))
    print(sv_position)

    # Calculate user's position
    xs = sv_position[['Sat.X', 'Sat.Y', 'Sat.Z']].to_numpy()
    pr = one_epoch['Pseudorange_Measurement'].to_numpy()
    x0 = np.array([0, 0, 0])
    b0 = 0
    try:
        x, b, _ = parser.least_squares(xs, pr, x0, b0)
        lla = navpy.ecef2lla(x)
        latest_position = lla
        print(f"Calculated position: {lla}")
        return jsonify({"status": "success", "position": lla}), 200
    except np.linalg.LinAlgError:
        print("Singular matrix encountered. Skipping this calculation.")
        return jsonify({"status": "failure", "error": "Singular matrix encountered"}), 400
    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({"status": "failure", "error": str(e)}), 400

@app.route('/gnssnavdata', methods=['POST'])
def receive_gnss_navdata():
    message = request.get_json()
    print("Received GNSS navigation message:", message)
    # Process the navigation message as needed
    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2121)
from flask import Flask, request, jsonify
import math
import random 
import os
import sys
import config 


app = Flask(__name__)

def process_request(x, alpha):
    """
    Mandotory computation function provided in the project document.
    Simulates a CPU-bound task with a heavy-tailed (Pareto) distribution.
    """

    #Draw a multiplier from the Pareto distribution
    multiplier = random.paretovariate(alpha)
    processing_time = x * multiplier

    #Perform fictitious computation to create real CPU load 
    accumulator = 0

    #The loop length is proportional to the calculated processing time
    for i in range(int(processing_time * 10**6)):
        accumulator += math.sin(i) * math.cos(i)

        return accumulator
    
@app.route('/process', methods=['POST'])
def handle_request():
    """"
    Endpoint to receive job requestss from the Dispatcher.
    Expects a JSON body with an 'x' value.
    """
    data = request.get_json()
    x = data.get('x', 1.0)

    #Execture the heavy-tailed task
    result = process_request(x, config.ALPHA)

    return jsonify({
        "status": "completed",
        "server_id": os.getpid(),
        "result": result
    })

if __name__ == '__main__':
    #Get port from command line argument
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5001

    #Ensure deterministic randomness for each server
    random.seed(config.INITIAL_SEED + port)

    #Start the Flask server
    app.run(host='0.0.0.0', port=port, threaded=False)
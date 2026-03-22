import tensorflow as tf

# Load the TensorFlow Lite model
model_file = 'model.tflite'
interpreter = tf.lite.Interpreter(model_path=model_file)
interpreter.allocate_tensors()

# Get input and output tensors
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# Function to make predictions
def predict(input_data):
    # Prepare input data
    input_data = input_data.reshape(input_details[0]['shape'])
    interpreter.set_tensor(input_details[0]['index'], input_data)
    interpreter.invoke()
    predictions = interpreter.get_tensor(output_details[0]['index'])
    return predictions

if __name__ == '__main__':
    # Example usage
    # Replace this with real-time data collection logic
    input_data = tf.constant([[0.0, 0.0, 0.0, 0.0]])  # Dummy input
    prediction = predict(input_data)
    print(f'Motor Activation Prediction: {prediction}')
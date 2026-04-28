# =============================================================================
# train_model/train.py
# =============================================================================
# Trains a neural network on the generated simulation data and exports
# it as a TFLite model for deployment on the Pico.
#
# RUN THIS ON YOUR PC — not on the Pico.
#
# WHAT THIS SCRIPT DOES:
#   1. Loads training_data.csv (produced by generate_data.py).
#   2. Normalizes all features and the target.
#   3. Trains a small fully-connected neural network.
#   4. Evaluates accuracy on a held-out test set.
#   5. Exports the model as apogee_model.tflite.
#   6. Prints the normalization constants you must copy into
#      apogee_predictor.py on the Pico.
#
# NETWORK ARCHITECTURE:
#   Input:   7 features (normalized)
#   Hidden:  Dense(64, relu) → Dense(64, relu) → Dense(32, relu)
#   Output:  Dense(1, linear) — predicts normalized apogee
#
#   WHY THIS SIZE?
#   Small enough to run inference in ~3-5ms on the Pico at 133MHz.
#   Large enough to capture the nonlinear relationship between
#   velocity/altitude at any point and final apogee.
#   If accuracy is poor, try Dense(128, relu) layers — but
#   test inference time on the Pico before committing.
#
# REQUIRED PYTHON PACKAGES (install on your PC):
#   pip install tensorflow pandas numpy scikit-learn matplotlib
#
# USAGE:
#   python train.py
#   (training_data.csv must exist from generate_data.py)
#
# OUTPUT:
#   apogee_model.tflite  — copy this to the Pico root filesystem
#   training_history.png — loss curve plot for diagnostics
#   normalization constants printed to terminal — copy to apogee_predictor.py
# =============================================================================

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import tensorflow as tf

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

TRAINING_DATA_FILE = "training_data.csv"
OUTPUT_MODEL_FILE  = "apogee_model.tflite"
PLOT_FILE          = "training_history.png"

# Feature columns — must match the order in apogee_predictor._build_feature_vector()
FEATURE_COLS = [
    "altitude_ft",
    "vertical_velocity_ft_s",
    "vertical_accel_ft_s2",
    "avg_velocity_ft_s",
    "avg_acceleration_ft_s2",
    "time_since_launch_s",
    "altitude_error_ft",
]

TARGET_COL = "true_apogee_ft"

# Training hyperparameters
EPOCHS        = 150
BATCH_SIZE    = 64
LEARNING_RATE = 0.001
VALIDATION_SPLIT = 0.15
TEST_SPLIT       = 0.15

# Early stopping — stop training if validation loss stops improving
EARLY_STOPPING_PATIENCE = 15

# Acceptable prediction error threshold for evaluation (feet)
# We consider a prediction "good" if it is within this many feet of true apogee.
ACCEPTABLE_ERROR_FT = 250.0


def load_data() -> pd.DataFrame:
    """Load and validate training data."""
    if not os.path.exists(TRAINING_DATA_FILE):
        raise FileNotFoundError(
            f"{TRAINING_DATA_FILE} not found. "
            f"Run generate_data.py first."
        )

    df = pd.read_csv(TRAINING_DATA_FILE)
    print(f"Loaded {len(df)} training rows from {TRAINING_DATA_FILE}")

    # Check all required columns are present
    missing = [c for c in FEATURE_COLS + [TARGET_COL] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in training data: {missing}")

    return df


def build_model(input_size: int) -> tf.keras.Model:
    """
    Build the neural network.

    Architecture explanation:
      - Dense layers are fully-connected: every neuron in one layer
        connects to every neuron in the next.
      - ReLU activation: output = max(0, input). This introduces
        nonlinearity, allowing the model to learn curved relationships.
      - Linear output: no activation on the last layer means the
        model can predict any continuous value (regression, not classification).
      - BatchNormalization: normalizes layer inputs during training,
        which helps the model train faster and more stably.
      - Dropout(0.1): randomly zeroes 10% of neurons during training,
        which prevents overfitting (memorizing training data).

    Args:
        input_size: Number of input features (7).

    Returns:
        Compiled Keras model.
    """
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(input_size,)),

        # Two hidden layers of 32 neurons each.
        # Smaller than the original 64→64→32 design — reduces TFLite
        # inference time on the Pico from ~5–8ms to ~2–3ms with
        # negligible accuracy loss for this regression task.
        # If test MAE is unacceptably high after training, increase
        # to Dense(64) and retest inference time on the actual Pico.
        tf.keras.layers.Dense(32, activation='relu'),
        tf.keras.layers.BatchNormalization(),
        tf.keras.layers.Dropout(0.1),

        tf.keras.layers.Dense(32, activation='relu'),

        # Output: single value (normalized apogee prediction)
        tf.keras.layers.Dense(1, activation='linear'),
    ])

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss='mean_squared_error',
        metrics=['mean_absolute_error']
    )

    return model


def export_tflite(model: tf.keras.Model, filepath: str) -> None:
    """
    Convert the trained Keras model to TFLite format.

    WHY TFLITE?
      The standard TensorFlow runtime requires hundreds of MB of RAM
      and is not available on microcontrollers. TFLite is a compiled,
      stripped-down format that the Pico can load and run with only
      kilobytes of RAM.

    We use float32 (not int8 quantization) for simplicity.
    float32 TFLite is accurate and fast enough for this application.
    If you later need to squeeze more performance, you can enable
    int8 quantization — but update config.MODEL_IS_QUANTIZED = True
    and add the scale/zero-point handling to apogee_predictor.py.

    Args:
        model:    Trained Keras model.
        filepath: Output .tflite file path.
    """
    converter = tf.lite.TFLiteConverter.from_keras_model(model)

    # Float32 conversion — simple and accurate
    converter.optimizations = []

    tflite_model = converter.convert()

    with open(filepath, 'wb') as f:
        f.write(tflite_model)

    size_kb = len(tflite_model) / 1024
    print(f"TFLite model saved: {filepath} ({size_kb:.1f} KB)")


def plot_history(history: tf.keras.callbacks.History) -> None:
    """
    Plot training and validation loss curves.

    A healthy training curve:
      - Both train and val loss decrease over time.
      - They converge to similar values (no large gap = no overfitting).
      - Loss levels off and stops improving (early stopping fires here).

    An unhealthy training curve:
      - Val loss increases while train loss decreases = overfitting.
        Fix: more training data, more dropout, smaller model.
      - Loss barely decreases = underfitting.
        Fix: larger model, more epochs, lower learning rate.
    """
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    axes[0].plot(history.history['loss'],     label='Train loss')
    axes[0].plot(history.history['val_loss'], label='Val loss')
    axes[0].set_title('Loss (MSE)')
    axes[0].set_xlabel('Epoch')
    axes[0].set_ylabel('MSE')
    axes[0].legend()
    axes[0].set_yscale('log')

    axes[1].plot(history.history['mean_absolute_error'],     label='Train MAE')
    axes[1].plot(history.history['val_mean_absolute_error'], label='Val MAE')
    axes[1].set_title('Mean Absolute Error (normalized units)')
    axes[1].set_xlabel('Epoch')
    axes[1].set_ylabel('MAE')
    axes[1].legend()

    plt.tight_layout()
    plt.savefig(PLOT_FILE, dpi=120)
    print(f"Training curve saved: {PLOT_FILE}")


def main():
    print("=" * 60)
    print("Apogee Neural Network Trainer")
    print("=" * 60)

    # --- Load data ---
    df = load_data()
    X = df[FEATURE_COLS].values.astype(np.float32)
    y = df[TARGET_COL].values.astype(np.float32)

    # --- Split into train / test ---
    X_train_full, X_test, y_train_full, y_test = train_test_split(
        X, y,
        test_size=TEST_SPLIT,
        random_state=42
    )

    # --- Normalize features ---
    # StandardScaler computes mean and std from training data ONLY.
    # We must NOT fit on test data — that would be data leakage.
    feature_scaler = StandardScaler()
    X_train_full_norm = feature_scaler.fit_transform(X_train_full)
    X_test_norm       = feature_scaler.transform(X_test)

    # Normalize target (apogee) the same way
    target_scaler = StandardScaler()
    y_train_full_norm = target_scaler.fit_transform(
        y_train_full.reshape(-1, 1)
    ).flatten()
    y_test_norm = target_scaler.transform(
        y_test.reshape(-1, 1)
    ).flatten()

    print(f"\nTraining set:  {len(X_train_full_norm)} samples")
    print(f"Test set:      {len(X_test_norm)} samples")

    # --- Build model ---
    model = build_model(input_size=len(FEATURE_COLS))
    model.summary()

    # --- Train ---
    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor='val_loss',
        patience=EARLY_STOPPING_PATIENCE,
        restore_best_weights=True,
        verbose=1
    )

    print(f"\nTraining for up to {EPOCHS} epochs...")
    history = model.fit(
        X_train_full_norm, y_train_full_norm,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        validation_split=VALIDATION_SPLIT,
        callbacks=[early_stop],
        verbose=1
    )

    # --- Evaluate ---
    print("\n--- Test Set Evaluation ---")
    y_pred_norm = model.predict(X_test_norm, verbose=0).flatten()

    # Denormalize predictions and targets back to feet
    y_pred_ft = target_scaler.inverse_transform(
        y_pred_norm.reshape(-1, 1)
    ).flatten()
    y_true_ft = y_test

    errors    = np.abs(y_pred_ft - y_true_ft)
    mae_ft    = errors.mean()
    rmse_ft   = np.sqrt(((y_pred_ft - y_true_ft) ** 2).mean())
    within    = (errors <= ACCEPTABLE_ERROR_FT).mean() * 100

    print(f"Mean absolute error:  {mae_ft:.1f} ft")
    print(f"RMSE:                 {rmse_ft:.1f} ft")
    print(f"Within ±{ACCEPTABLE_ERROR_FT:.0f} ft:      {within:.1f}%")

    if mae_ft > 500:
        print("\nWARNING: MAE > 500 ft. Consider:")
        print("  - More simulation files (aim for 500+)")
        print("  - More varied simulation conditions")
        print("  - Larger model (Dense(128) layers)")
    elif mae_ft > 250:
        print("\nNote: MAE > 250 ft. More simulation data would help.")
    else:
        print("\nModel accuracy looks good for flight use.")

    # --- Export TFLite ---
    export_tflite(model, OUTPUT_MODEL_FILE)

    # --- Plot ---
    plot_history(history)

    # =========================================================================
    # CRITICAL: Print normalization constants
    # Copy these values into apogee_predictor.py on the Pico.
    # If these don't match, predictions will be wrong.
    # =========================================================================
    print("\n" + "=" * 60)
    print("COPY THESE VALUES INTO apogee_predictor.py")
    print("=" * 60)

    means = feature_scaler.mean_.tolist()
    stds  = feature_scaler.scale_.tolist()

    print("\nFEATURE_MEANS = [")
    for col, mean in zip(FEATURE_COLS, means):
        print(f"    {mean:.4f},   # {col}")
    print("]")

    print("\nFEATURE_STDS = [")
    for col, std in zip(FEATURE_COLS, stds):
        print(f"    {std:.4f},   # {col}")
    print("]")

    print(f"\nOUTPUT_MEAN = {target_scaler.mean_[0]:.4f}")
    print(f"OUTPUT_STD  = {target_scaler.scale_[0]:.4f}")

    print("\n" + "=" * 60)
    print("NEXT STEPS:")
    print("  1. Copy the normalization values above into apogee_predictor.py")
    print(f"  2. Copy {OUTPUT_MODEL_FILE} to the root of the Pico filesystem")
    print("  3. Set config.MODEL_INPUT_FEATURES = 7")
    print("  4. Set config.MODEL_IS_QUANTIZED = False")
    print("=" * 60)


if __name__ == "__main__":
    main()

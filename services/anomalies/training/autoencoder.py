"""SageMaker training script for the anomaly detection autoencoder.

Architecture:
- Encoder: Input → Dense(64, relu) → Dense(32, relu) → Dense(encoding_dim, relu)
- Decoder: Dense(32, relu) → Dense(64, relu) → Dense(n_features, sigmoid)

Training:
- Loss: MSE (Mean Squared Error)
- Optimizer: Adam
- Early stopping: patience=10 on validation loss
- Threshold: 95th percentile of reconstruction errors on training data

Outputs saved to S3:
- Model artifact (SavedModel format)
- Normalization statistics (mean, std per feature)
- Threshold value

Requirements: 12.1, 12.2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, Model
from tensorflow.keras.callbacks import EarlyStopping
from sklearn.preprocessing import StandardScaler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_autoencoder(n_features: int, encoding_dim: int) -> Model:
    """Build the autoencoder model.

    Architecture:
    - Encoder: Input → Dense(64, relu) → Dense(32, relu) → Dense(encoding_dim, relu)
    - Decoder: Dense(32, relu) → Dense(64, relu) → Dense(n_features, sigmoid)

    Args:
        n_features: Number of input features.
        encoding_dim: Dimension of the encoding layer (bottleneck).

    Returns:
        Compiled Keras autoencoder model.
    """
    # Encoder
    input_layer = keras.Input(shape=(n_features,))
    encoded = layers.Dense(64, activation="relu")(input_layer)
    encoded = layers.Dense(32, activation="relu")(encoded)
    encoded = layers.Dense(encoding_dim, activation="relu")(encoded)

    # Decoder
    decoded = layers.Dense(32, activation="relu")(encoded)
    decoded = layers.Dense(64, activation="relu")(decoded)
    decoded = layers.Dense(n_features, activation="sigmoid")(decoded)

    autoencoder = Model(input_layer, decoded)
    return autoencoder


def compute_threshold(model: Model, data: np.ndarray, percentile: float = 95.0) -> float:
    """Compute the anomaly detection threshold.

    The threshold is the 95th percentile of reconstruction errors
    on the training data.

    Args:
        model: Trained autoencoder model.
        data: Normalized training data.
        percentile: Percentile for threshold (default 95th).

    Returns:
        The computed threshold value.
    """
    predictions = model.predict(data, verbose=0)
    mse_per_sample = np.mean(np.power(data - predictions, 2), axis=1)
    threshold = float(np.percentile(mse_per_sample, percentile))
    logger.info(f"Computed threshold at {percentile}th percentile: {threshold:.6f}")
    return threshold


def train(args: argparse.Namespace) -> None:
    """Main training function.

    Loads data, normalizes, trains autoencoder, computes threshold,
    and saves all artifacts.

    Args:
        args: Parsed command-line arguments with hyperparameters and paths.
    """
    # Load training data
    training_dir = args.training
    data_files = [f for f in os.listdir(training_dir) if f.endswith((".csv", ".parquet"))]

    if not data_files:
        raise ValueError(f"No training data found in {training_dir}")

    # Load first file (support CSV and Parquet)
    data_path = os.path.join(training_dir, data_files[0])
    if data_path.endswith(".parquet"):
        df = pd.read_parquet(data_path)
    else:
        df = pd.read_csv(data_path)

    logger.info(f"Loaded training data: {df.shape[0]} records, {df.shape[1]} features")

    # Select only numeric columns
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.empty:
        raise ValueError("No numeric columns found in training data")

    n_features = numeric_df.shape[1]
    logger.info(f"Using {n_features} numeric features for training")

    # Normalize data using StandardScaler
    scaler = StandardScaler()
    normalized_data = scaler.fit_transform(numeric_df.values)

    # Clip to [0, 1] range for sigmoid output
    normalized_data = np.clip(normalized_data, 0, 1)

    # Split into train/validation (80/20)
    split_idx = int(len(normalized_data) * 0.8)
    train_data = normalized_data[:split_idx]
    val_data = normalized_data[split_idx:]

    logger.info(f"Training set: {train_data.shape[0]} samples")
    logger.info(f"Validation set: {val_data.shape[0]} samples")

    # Build model
    encoding_dim = int(args.encoding_dimension)
    model = build_autoencoder(n_features, encoding_dim)

    # Compile with MSE loss and Adam optimizer
    learning_rate = float(args.learning_rate)
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss="mse",
    )

    model.summary(print_fn=logger.info)

    # Early stopping callback (patience=10)
    early_stopping = EarlyStopping(
        monitor="val_loss",
        patience=10,
        restore_best_weights=True,
        verbose=1,
    )

    # Train
    epochs = int(args.epochs)
    batch_size = int(args.batch_size)

    history = model.fit(
        train_data,
        train_data,  # Autoencoder: input == target
        epochs=epochs,
        batch_size=batch_size,
        validation_data=(val_data, val_data),
        callbacks=[early_stopping],
        verbose=1,
    )

    final_loss = history.history["loss"][-1]
    final_val_loss = history.history["val_loss"][-1]
    logger.info(f"Training complete. Loss: {final_loss:.6f}, Val Loss: {final_val_loss:.6f}")

    # Compute anomaly threshold (95th percentile)
    threshold = compute_threshold(model, train_data)

    # Save model
    model_dir = args.model_dir
    model_path = os.path.join(model_dir, "autoencoder_model")
    model.save(model_path)
    logger.info(f"Model saved to {model_path}")

    # Save normalization statistics
    normalization_stats = {
        "mean": scaler.mean_.tolist(),
        "std": scaler.scale_.tolist(),
        "feature_names": numeric_df.columns.tolist(),
        "n_features": n_features,
        "encoding_dim": encoding_dim,
    }

    stats_path = os.path.join(model_dir, "normalization_stats.json")
    with open(stats_path, "w") as f:
        json.dump(normalization_stats, f, indent=2)
    logger.info(f"Normalization stats saved to {stats_path}")

    # Save threshold
    threshold_info = {
        "threshold": threshold,
        "percentile": 95.0,
        "training_samples": len(train_data),
        "training_loss": float(final_loss),
        "validation_loss": float(final_val_loss),
        "epochs_trained": len(history.history["loss"]),
    }

    threshold_path = os.path.join(model_dir, "threshold.json")
    with open(threshold_path, "w") as f:
        json.dump(threshold_info, f, indent=2)
    logger.info(f"Threshold info saved to {threshold_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train anomaly detection autoencoder")

    # Hyperparameters
    parser.add_argument("--learning_rate", type=float, default=0.001)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--encoding_dimension", type=int, default=16)

    # SageMaker environment variables
    parser.add_argument("--training", type=str, default=os.environ.get("SM_CHANNEL_TRAINING", "/opt/ml/input/data/training"))
    parser.add_argument("--model_dir", type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))

    args = parser.parse_args()
    train(args)

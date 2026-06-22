"""
Training script for GPT-2 model using PyTorch Lightning
"""

import argparse
import os
from pathlib import Path

import pytorch_lightning as pl
import torch
import yaml
from pytorch_lightning.callbacks import (
    LearningRateMonitor,
    ModelCheckpoint,
    EarlyStopping,
)
from pytorch_lightning.loggers import TensorBoardLogger

from data_module import WikiLMDataModule
from lit_gpt import LitGPT2


def load_config(config_path: str) -> dict:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        Dictionary containing configuration parameters
    """
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config


def calculate_total_steps(
    num_train_samples: int,
    batch_size: int,
    num_epochs: int,
    accumulate_grad_batches: int = 1,
) -> int:
    """
    Calculate total training steps for learning rate scheduler.

    Args:
        num_train_samples: Number of training samples
        batch_size: Batch size
        num_epochs: Number of training epochs
        accumulate_grad_batches: Gradient accumulation steps

    Returns:
        Total number of training steps
    """
    steps_per_epoch = num_train_samples // (batch_size * accumulate_grad_batches)
    total_steps = steps_per_epoch * num_epochs
    return total_steps


def setup_callbacks(cfg: dict) -> list:
    """
    Setup PyTorch Lightning callbacks.

    Args:
        cfg: Configuration dictionary

    Returns:
        List of callback objects
    """
    callbacks = []

    # Checkpoint callback - save best models based on validation loss
    checkpoint_callback = ModelCheckpoint(
        monitor="val_loss",
        mode="min",
        save_top_k=3,
        filename="gpt2-{epoch:02d}-{val_loss:.4f}",
        save_last=True,
        verbose=True,
    )
    callbacks.append(checkpoint_callback)

    # Checkpoint callback - save every epoch
    epoch_checkpoint_callback = ModelCheckpoint(
        every_n_epochs=1,
        filename="gpt2-epoch-{epoch:02d}",
        save_top_k=-1,  # Save all epoch checkpoints
        verbose=False,
    )
    callbacks.append(epoch_checkpoint_callback)

    # Learning rate monitor
    lr_monitor = LearningRateMonitor(logging_interval="step")
    callbacks.append(lr_monitor)

    # Early stopping (optional)
    if cfg.get("training", {}).get("early_stopping", False):
        early_stop_callback = EarlyStopping(
            monitor="val_loss",
            patience=cfg["training"].get("early_stopping_patience", 3),
            mode="min",
            verbose=True,
        )
        callbacks.append(early_stop_callback)

    return callbacks


def main(config_path: str):
    """
    Main training function.

    Args:
        config_path: Path to configuration file
    """
    # Load configuration
    cfg = load_config(config_path)
    print("Configuration loaded:")
    print(yaml.dump(cfg, default_flow_style=False))

    # Set random seed for reproducibility
    pl.seed_everything(cfg.get("seed", 42), workers=True)

    # Enable optimizations for modern GPUs
    if torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8:
        torch.set_float32_matmul_precision("medium")
        print("Using medium precision for matrix operations (Ampere GPU detected)")

    # Initialize data module
    print("\nInitializing data module...")
    data_module = WikiLMDataModule(
        train_path=cfg["data"]["train_path"],
        val_path=cfg["data"]["val_path"],
        tokenizer_name=cfg.get("tokenizer_name", "gpt2"),
        block_size=cfg["data"]["block_size"],
        train_batch_size=cfg["data"]["train_batch_size"],
        val_batch_size=cfg["data"]["val_batch_size"],
        num_workers=cfg["data"].get("num_workers", 4),
        preprocessing_num_workers=cfg["data"].get("preprocessing_num_workers", 4),
    )

    # Setup data to get dataset sizes
    data_module.setup("fit")

    # Calculate total training steps
    accumulate_grad_batches = cfg["training"].get("accumulate_grad_batches", 1)
    total_steps = calculate_total_steps(
        num_train_samples=len(data_module.train_dataset),
        batch_size=cfg["data"]["train_batch_size"],
        num_epochs=cfg["training"]["max_epochs"],
        accumulate_grad_batches=accumulate_grad_batches,
    )

    print(f"Total training steps: {total_steps}")

    # Initialize model
    print("\nInitializing model...")
    model = LitGPT2(
        model_size=cfg.get("model_size", "small"),
        vocab_size=data_module.tokenizer.vocab_size,
        n_positions=cfg["data"]["block_size"],
        learning_rate=cfg["training"]["learning_rate"],
        weight_decay=cfg["training"]["weight_decay"],
        warmup_steps=cfg["training"]["warmup_steps"],
        total_steps=total_steps,
    )

    # Setup callbacks
    callbacks = setup_callbacks(cfg)

    # Setup logger
    logger = TensorBoardLogger(
        save_dir=cfg["training"].get("default_root_dir", "outputs"),
        name=cfg.get("experiment_name", "gpt2_training"),
    )

    # Initialize trainer
    print("\nInitializing trainer...")
    trainer = pl.Trainer(
        max_epochs=cfg["training"]["max_epochs"],
        accelerator=cfg["training"].get("accelerator", "auto"),
        devices=cfg["training"].get("devices", 1),
        precision=cfg["training"].get("precision", 32),
        gradient_clip_val=cfg["training"].get("gradient_clip_val", 1.0),
        accumulate_grad_batches=accumulate_grad_batches,
        log_every_n_steps=cfg["training"].get("log_every_n_steps", 50),
        callbacks=callbacks,
        logger=logger,
        default_root_dir=cfg["training"].get("default_root_dir", "outputs"),
        enable_checkpointing=True,
        deterministic=False,
    )

    # Train the model
    print("\nStarting training...")
    trainer.fit(model, data_module)

    # Print best model path
    best_model_path = trainer.checkpoint_callback.best_model_path
    print(f"\nTraining completed!")
    print(f"Best model saved at: {best_model_path}")
    print(f"Best validation loss: {trainer.checkpoint_callback.best_model_score:.4f}")


def generate_text(checkpoint_path: str, prompt: str, max_length: int = 100):
    """
    Generate text using a trained model.

    Args:
        checkpoint_path: Path to model checkpoint
        prompt: Text prompt for generation
        max_length: Maximum length of generated text
    """
    # Load model from checkpoint
    model = LitGPT2.load_from_checkpoint(checkpoint_path, map_location="cpu")
    model.eval()

    # Move model to CPU to avoid MPS issues
    model = model.to("cpu")

    # Load tokenizer
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained("gpt2")

    # Encode prompt
    input_ids = tokenizer.encode(prompt, return_tensors="pt")

    # Make sure input is on CPU
    input_ids = input_ids.to("cpu")

    # Generate
    output_ids = model.generate(
        input_ids=input_ids,
        max_length=max_length,
        temperature=0.8,
        top_k=50,
    )

    # Decode
    generated_text = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    print(f"\nPrompt: {prompt}")
    print(f"Generated: {generated_text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train GPT-2 model")
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate text instead of training",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        help="Path to checkpoint for generation",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="Once upon a time",
        help="Text prompt for generation",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=100,
        help="Maximum length for text generation",
    )

    args = parser.parse_args()

    if args.generate:
        if not args.checkpoint:
            print("Error: --checkpoint required for text generation")
            exit(1)
        generate_text(args.checkpoint, args.prompt, args.max_length)
    else:
        main(args.config)

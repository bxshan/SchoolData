"""
Script to prepare GPT-2 training and validation data from Wikipedia JSONL file.
Generates datasets for different model configurations (tiny, small, medium, large).
Each configuration gets appropriate data size:
- tiny: 10K train, 1K val (for quick experimentation)
- small: 50K train, 5K val
- medium: 100K train, 10K val
- large: 180K train, 20K val (full dataset)
"""

import json
import random
from pathlib import Path
from typing import Dict, List


# Model configuration data sizes
MODEL_CONFIGS = {
    "tiny": {
        "train_samples": 10_000,
        "val_samples": 1_000,
        "description": "Quick experimentation"
    },
    "small": {
        "train_samples": 50_000,
        "val_samples": 5_000,
        "description": "Small-scale training"
    },
    "medium": {
        "train_samples": 100_000,
        "val_samples": 10_000,
        "description": "Medium-scale training"
    },
    "large": {
        "train_samples": 180_000,
        "val_samples": 20_000,
        "description": "Full dataset training"
    }
}


def load_all_data(input_file: str) -> List[Dict]:
    """
    Load all data from JSONL file.

    Args:
        input_file: Path to input JSONL file

    Returns:
        List of article dictionaries with 'text' field
    """
    print(f"Loading data from {input_file}...")
    data = []
    with open(input_file, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            try:
                item = json.loads(line.strip())
                if "text" in item:
                    data.append({"text": item["text"]})
                else:
                    print(f"Warning: Line {line_num} has no 'text' field")
            except json.JSONDecodeError as e:
                print(f"Error parsing line {line_num}: {e}")

    print(f"Loaded {len(data)} articles total")
    return data


def prepare_data_for_config(
    data: List[Dict],
    config_name: str,
    output_base_dir: str,
    random_seed: int = 42
):
    """
    Prepare training and validation data for a specific model configuration.

    Args:
        data: Full dataset (already shuffled)
        config_name: Name of the model config ('tiny', 'small', 'medium', 'large')
        output_base_dir: Base directory for output (e.g., 'data')
        random_seed: Random seed for reproducibility
    """
    if config_name not in MODEL_CONFIGS:
        raise ValueError(f"Unknown config: {config_name}. Available: {list(MODEL_CONFIGS.keys())}")

    config = MODEL_CONFIGS[config_name]
    train_samples = config["train_samples"]
    val_samples = config["val_samples"]
    total_needed = train_samples + val_samples

    print(f"\n{'='*60}")
    print(f"Preparing data for '{config_name}' configuration")
    print(f"Description: {config['description']}")
    print(f"Train samples: {train_samples:,}")
    print(f"Val samples: {val_samples:,}")
    print(f"{'='*60}")

    # Check if we have enough data
    if total_needed > len(data):
        print(f"Warning: Requested {total_needed:,} samples but only {len(data):,} available")
        print(f"Using all available data...")
        train_samples = int(len(data) * 0.9)
        val_samples = len(data) - train_samples

    # Create output directory
    output_dir = Path(output_base_dir) / config_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Split data
    train_data = data[:train_samples]
    val_data = data[train_samples:train_samples + val_samples]

    # Write training data
    train_file = output_dir / "train.jsonl"
    print(f"Writing training data to {train_file}...")
    with open(train_file, "w", encoding="utf-8") as f:
        for item in train_data:
            json.dump(item, f, ensure_ascii=False)
            f.write("\n")

    # Write validation data
    val_file = output_dir / "val.jsonl"
    print(f"Writing validation data to {val_file}...")
    with open(val_file, "w", encoding="utf-8") as f:
        for item in val_data:
            json.dump(item, f, ensure_ascii=False)
            f.write("\n")

    print(f"Done! Files created:")
    print(f"  - {train_file} ({len(train_data):,} samples)")
    print(f"  - {val_file} ({len(val_data):,} samples)")


def prepare_all_configs(
    input_file: str,
    output_base_dir: str = "data",
    configs: List[str] = None,
    random_seed: int = 42
):
    """
    Prepare data for all or selected model configurations.

    Args:
        input_file: Path to input JSONL file
        output_base_dir: Base directory for output
        configs: List of config names to prepare. If None, prepares all configs.
        random_seed: Random seed for reproducibility
    """
    # Load and shuffle all data once
    random.seed(random_seed)
    data = load_all_data(input_file)

    print(f"\nShuffling data with seed {random_seed}...")
    random.shuffle(data)

    # Determine which configs to prepare
    if configs is None:
        configs = list(MODEL_CONFIGS.keys())

    # Prepare data for each configuration
    for config_name in configs:
        prepare_data_for_config(data, config_name, output_base_dir, random_seed)

    print(f"\n{'='*60}")
    print("All configurations prepared successfully!")
    print(f"{'='*60}")
    print("\nData directory structure:")
    base_path = Path(output_base_dir)
    for config_name in configs:
        config_path = base_path / config_name
        if config_path.exists():
            print(f"\n{config_name}/")
            for file in sorted(config_path.glob("*.jsonl")):
                size_mb = file.stat().st_size / (1024 * 1024)
                print(f"  - {file.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Prepare GPT-2 training data for different model configurations"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="data_src/wiki/raw_200k/wikipedia_200k_random.jsonl",
        help="Path to input JSONL file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data",
        help="Base output directory"
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        choices=list(MODEL_CONFIGS.keys()),
        default=None,
        help="Model configs to prepare (default: all)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility"
    )

    args = parser.parse_args()

    prepare_all_configs(
        input_file=args.input,
        output_base_dir=args.output,
        configs=args.configs,
        random_seed=args.seed
    )

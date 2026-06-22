"""
Data Module for GPT-2 Training
Handles data loading, tokenization, and batching for language model training
"""

import json
from pathlib import Path
from typing import Optional

import pytorch_lightning as pl
from datasets import Dataset
from torch.utils.data import DataLoader
from transformers import AutoTokenizer, DataCollatorForLanguageModeling


class WikiLMDataModule(pl.LightningDataModule):
    """
    PyTorch Lightning Data Module for language model training.

    This module handles:
    - Loading JSONL formatted text files
    - Tokenization using HuggingFace tokenizers
    - Text grouping into fixed-size blocks
    - Dynamic batch preparation with data collation
    """

    def __init__(
        self,
        train_path: str,
        val_path: str,
        tokenizer_name: str = "gpt2",
        block_size: int = 128,
        train_batch_size: int = 32,
        val_batch_size: int = 32,
        num_workers: int = 4,
        preprocessing_num_workers: int = 4,
    ):
        """
        Initialize the data module.

        Args:
            train_path: Path to training data JSONL file
            val_path: Path to validation data JSONL file
            tokenizer_name: Name of the HuggingFace tokenizer to use
            block_size: Size of text blocks for training (sequence length)
            train_batch_size: Batch size for training
            val_batch_size: Batch size for validation
            num_workers: Number of workers for data loading
            preprocessing_num_workers: Number of workers for preprocessing
        """
        super().__init__()
        self.save_hyperparameters()

        self.train_path = train_path
        self.val_path = val_path
        self.tokenizer_name = tokenizer_name
        self.block_size = block_size
        self.train_batch_size = train_batch_size
        self.val_batch_size = val_batch_size
        self.num_workers = num_workers
        self.preprocessing_num_workers = preprocessing_num_workers

        # Initialize tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)

        # Set pad token to eos token if not defined
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        # Initialize data collator for causal language modeling
        self.data_collator = DataCollatorForLanguageModeling(
            tokenizer=self.tokenizer,
            mlm=False,  # Causal LM, not masked LM
        )

        self.train_dataset = None
        self.val_dataset = None

    def prepare_data(self):
        """
        Download and prepare data (called only on 1 GPU/TPU).
        This method is used to download tokenizer if needed.
        """
        # Download tokenizer if needed
        AutoTokenizer.from_pretrained(self.tokenizer_name)

    def setup(self, stage: Optional[str] = None):
        """
        Setup datasets for training and validation.

        Args:
            stage: Current stage ('fit', 'validate', 'test', or 'predict')
        """
        if stage == "fit" or stage is None:
            # Load training data
            self.train_dataset = self._load_and_process_data(
                self.train_path,
                is_train=True
            )

            # Load validation data
            self.val_dataset = self._load_and_process_data(
                self.val_path,
                is_train=False
            )

            print(f"Training dataset size: {len(self.train_dataset)}")
            print(f"Validation dataset size: {len(self.val_dataset)}")

    def _load_and_process_data(self, file_path: str, is_train: bool) -> Dataset:
        """
        Load JSONL file and process it for language modeling.

        Args:
            file_path: Path to JSONL file
            is_train: Whether this is training data

        Returns:
            Processed HuggingFace Dataset
        """
        # Load JSONL file
        data = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line.strip())
                data.append(item)

        # Convert to HuggingFace Dataset
        dataset = Dataset.from_list(data)

        # Tokenize the dataset
        tokenized_dataset = dataset.map(
            self._tokenize_function,
            batched=True,
            num_proc=self.preprocessing_num_workers,
            remove_columns=dataset.column_names,
            desc=f"Tokenizing {'training' if is_train else 'validation'} data",
        )

        # Group texts into blocks
        grouped_dataset = tokenized_dataset.map(
            self._group_texts,
            batched=True,
            num_proc=self.preprocessing_num_workers,
            desc=f"Grouping {'training' if is_train else 'validation'} texts",
        )

        return grouped_dataset

    def _tokenize_function(self, examples):
        """
        Tokenize text examples.

        Args:
            examples: Dictionary with 'text' field containing text strings

        Returns:
            Dictionary with tokenized outputs
        """
        return self.tokenizer(
            examples["text"],
            truncation=False,
            padding=False,
        )

    def _group_texts(self, examples):
        """
        Group tokenized texts into fixed-size blocks.

        Args:
            examples: Dictionary with 'input_ids' and 'attention_mask'

        Returns:
            Dictionary with grouped inputs
        """
        # Concatenate all texts
        concatenated_examples = {k: sum(examples[k], []) for k in examples.keys()}
        total_length = len(concatenated_examples["input_ids"])

        # Drop the small remainder
        # We could add padding instead, but this is simpler
        if total_length >= self.block_size:
            total_length = (total_length // self.block_size) * self.block_size

        # Split by chunks of block_size
        result = {
            k: [
                concatenated_examples[k][i : i + self.block_size]
                for i in range(0, total_length, self.block_size)
            ]
            for k in concatenated_examples.keys()
        }

        # Create labels (same as input_ids for causal LM)
        result["labels"] = result["input_ids"].copy()

        return result

    def train_dataloader(self) -> DataLoader:
        """
        Create training data loader.

        Returns:
            DataLoader for training
        """
        return DataLoader(
            self.train_dataset,
            batch_size=self.train_batch_size,
            shuffle=True,
            num_workers=self.num_workers,
            collate_fn=self.data_collator,
            pin_memory=True,
        )

    def val_dataloader(self) -> DataLoader:
        """
        Create validation data loader.

        Returns:
            DataLoader for validation
        """
        return DataLoader(
            self.val_dataset,
            batch_size=self.val_batch_size,
            shuffle=False,
            num_workers=self.num_workers,
            collate_fn=self.data_collator,
            pin_memory=True,
        )


def create_sample_data(output_dir: str, num_train_samples: int = 100, num_val_samples: int = 20):
    """
    Create sample JSONL files for testing.

    Args:
        output_dir: Directory to save sample data
        num_train_samples: Number of training samples
        num_val_samples: Number of validation samples
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    sample_texts = [
        "The quick brown fox jumps over the lazy dog.",
        "Machine learning is a subset of artificial intelligence.",
        "Python is a popular programming language for data science.",
        "Natural language processing enables computers to understand human language.",
        "Deep learning models have revolutionized computer vision.",
    ]

    # Create training data
    train_file = output_path / "train.jsonl"
    with open(train_file, "w", encoding="utf-8") as f:
        for i in range(num_train_samples):
            text = sample_texts[i % len(sample_texts)]
            json.dump({"text": text}, f)
            f.write("\n")

    # Create validation data
    val_file = output_path / "val.jsonl"
    with open(val_file, "w", encoding="utf-8") as f:
        for i in range(num_val_samples):
            text = sample_texts[i % len(sample_texts)]
            json.dump({"text": text}, f)
            f.write("\n")

    print(f"Sample data created in {output_dir}")
    print(f"Training samples: {num_train_samples}")
    print(f"Validation samples: {num_val_samples}")


if __name__ == "__main__":
    # Create sample data for testing
    create_sample_data("data/sample", num_train_samples=100, num_val_samples=20)

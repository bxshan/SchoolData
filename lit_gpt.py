"""
GPT-2 Model Implementation using PyTorch Lightning
Based on HuggingFace's GPT2LMHeadModel
"""

import pytorch_lightning as pl
import torch
from torch.optim import AdamW
from transformers import GPT2Config, GPT2LMHeadModel
from transformers.optimization import get_linear_schedule_with_warmup


class LitGPT2(pl.LightningModule):
    """
    PyTorch Lightning wrapper for GPT2 language model training.

    This class handles:
    - Model initialization with custom configurations
    - Forward pass delegation to HuggingFace's GPT2LMHeadModel
    - Training and validation steps
    - Optimizer and scheduler configuration
    """

    def __init__(
        self,
        model_size: str = "small",
        vocab_size: int = 50257,
        n_positions: int = 1024,
        learning_rate: float = 2e-4,
        weight_decay: float = 0.01,
        warmup_steps: int = 100,
        total_steps: int = 10000,
    ):
        """
        Initialize the GPT2 Lightning Module.

        Args:
            model_size: Model size configuration ('tiny', 'small', 'medium', 'large')
            vocab_size: Size of vocabulary
            n_positions: Maximum sequence length for positional embeddings
            learning_rate: Learning rate for optimizer
            weight_decay: Weight decay for AdamW optimizer
            warmup_steps: Number of warmup steps for learning rate scheduler
            total_steps: Total number of training steps
        """
        super().__init__()
        self.save_hyperparameters()

        # Build GPT2 configuration based on model size
        config = self.build_gpt2_config(
            model_size=model_size,
            vocab_size=vocab_size,
            n_positions=n_positions
        )

        # Initialize GPT2 model with custom config
        self.model = GPT2LMHeadModel(config)

        # Store training parameters
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.warmup_steps = warmup_steps
        self.total_steps = total_steps

        # Log model size
        num_params = sum(p.numel() for p in self.parameters())
        print(f"Model initialized with {num_params:,} parameters")

    @staticmethod
    def build_gpt2_config(
        model_size: str,
        vocab_size: int,
        n_positions: int
    ) -> GPT2Config:
        """
        Build GPT2 configuration based on model size.

        Args:
            model_size: Size identifier ('tiny', 'small', 'medium', 'large')
            vocab_size: Vocabulary size
            n_positions: Maximum sequence length

        Returns:
            GPT2Config object with appropriate parameters
        """
        configs = {
            "tiny": {
                "n_layer": 4,
                "n_head": 4,
                "n_embd": 256,
            },
            "small": {
                "n_layer": 12,
                "n_head": 12,
                "n_embd": 768,
            },
            "medium": {
                "n_layer": 24,
                "n_head": 16,
                "n_embd": 1024,
            },
            "large": {
                "n_layer": 36,
                "n_head": 20,
                "n_embd": 1280,
            }
        }

        if model_size not in configs:
            raise ValueError(
                f"Invalid model_size: {model_size}. "
                f"Choose from {list(configs.keys())}"
            )

        config_params = configs[model_size]

        return GPT2Config(
            vocab_size=vocab_size,
            n_positions=n_positions,
            n_embd=config_params["n_embd"],
            n_layer=config_params["n_layer"],
            n_head=config_params["n_head"],
            resid_pdrop=0.1,
            embd_pdrop=0.1,
            attn_pdrop=0.1,
        )

    def forward(self, input_ids, attention_mask=None, labels=None):
        """
        Forward pass through GPT2 model.

        Args:
            input_ids: Token IDs of shape (batch_size, sequence_length)
            attention_mask: Attention mask of shape (batch_size, sequence_length)
            labels: Labels for language modeling loss (same shape as input_ids)

        Returns:
            Model outputs including loss (if labels provided) and logits
        """
        return self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            labels=labels,
        )

    def training_step(self, batch, batch_idx):
        """
        Training step for a single batch.

        Args:
            batch: Dictionary containing input_ids, attention_mask, and labels
            batch_idx: Index of the current batch

        Returns:
            Loss tensor
        """
        outputs = self(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"],
        )

        loss = outputs.loss

        # Log training loss
        self.log("train_loss", loss, prog_bar=True, on_step=True, on_epoch=True)

        return loss

    def validation_step(self, batch, batch_idx):
        """
        Validation step for a single batch.

        Args:
            batch: Dictionary containing input_ids, attention_mask, and labels
            batch_idx: Index of the current batch

        Returns:
            Loss tensor
        """
        outputs = self(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            labels=batch["labels"],
        )

        loss = outputs.loss

        # Calculate perplexity
        perplexity = torch.exp(loss)

        # Log validation metrics
        self.log("val_loss", loss, prog_bar=True, on_step=False, on_epoch=True)
        self.log("val_perplexity", perplexity, prog_bar=True, on_step=False, on_epoch=True)

        return loss

    def configure_optimizers(self):
        """
        Configure optimizer and learning rate scheduler.

        Returns:
            Dictionary containing optimizer and scheduler configuration
        """
        # Separate parameters for weight decay
        # Don't apply weight decay to bias and LayerNorm parameters
        no_decay = ["bias", "LayerNorm.weight"]
        optimizer_grouped_parameters = [
            {
                "params": [
                    p for n, p in self.named_parameters()
                    if not any(nd in n for nd in no_decay)
                ],
                "weight_decay": self.weight_decay,
            },
            {
                "params": [
                    p for n, p in self.named_parameters()
                    if any(nd in n for nd in no_decay)
                ],
                "weight_decay": 0.0,
            },
        ]

        # Initialize AdamW optimizer
        optimizer = AdamW(
            optimizer_grouped_parameters,
            lr=self.learning_rate,
            betas=(0.9, 0.95),
            eps=1e-8,
        )

        # Initialize linear warmup + linear decay scheduler
        scheduler = get_linear_schedule_with_warmup(
            optimizer,
            num_warmup_steps=self.warmup_steps,
            num_training_steps=self.total_steps,
        )

        return {
            "optimizer": optimizer,
            "lr_scheduler": {
                "scheduler": scheduler,
                "interval": "step",
                "frequency": 1,
            },
        }

    def generate(self, input_ids, max_length=100, temperature=1.0, top_k=50):
        """
        Generate text using the trained model.

        Args:
            input_ids: Starting token IDs
            max_length: Maximum length of generated sequence
            temperature: Sampling temperature
            top_k: Top-k sampling parameter

        Returns:
            Generated token IDs
        """
        self.model.eval()

        # Get model's maximum position embeddings
        max_position_embeddings = self.model.config.n_positions

        # Cap max_length to model's maximum position
        if max_length > max_position_embeddings:
            print(f"Warning: Requested max_length ({max_length}) exceeds model's max position ({max_position_embeddings})")
            print(f"Setting max_length to {max_position_embeddings}")
            max_length = max_position_embeddings

        # Check if prompt is too long
        prompt_length = input_ids.shape[1]
        if prompt_length >= max_position_embeddings:
            print(f"Error: Prompt length ({prompt_length}) exceeds model's max position ({max_position_embeddings})")
            print(f"Truncating prompt to {max_position_embeddings - 1} tokens")
            input_ids = input_ids[:, :max_position_embeddings - 1]
            prompt_length = input_ids.shape[1]

        # Ensure we have room to generate at least a few tokens
        if prompt_length >= max_length - 10:
            max_length = min(prompt_length + 50, max_position_embeddings)
            print(f"Adjusting max_length to {max_length} to allow generation")

        with torch.no_grad():
            output = self.model.generate(
                input_ids=input_ids,
                max_length=max_length,
                temperature=temperature,
                top_k=top_k,
                do_sample=True,
                pad_token_id=self.model.config.eos_token_id,
            )
        return output

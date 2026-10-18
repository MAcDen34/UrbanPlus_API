from pathlib import Path
from model import train_and_save

ROOT = Path(__file__).parent.parent

if __name__ == "__main__":
     train_and_save(
          ROOT / "data/processed/population.csv",
          ROOT / "models/population_model.joblib",
          ROOT / "data/processed/validation.csv"
     )

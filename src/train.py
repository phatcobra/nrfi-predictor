"""Model training for NRFI/YRFI prediction.

Train LightGBM models with:
- Historical data from Snowflake
- Feature engineering pipeline
- Time-series cross-validation
- Calibration for reliable probabilities
- Model versioning and tracking
- Sentry error monitoring
- PostHog analytics
"""

import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score, log_loss
import joblib
import json
from datetime import datetime, timedelta
from typing import Dict, Tuple, List
import logging
import os
import sentry_sdk
from snowflake_loader import SnowflakeLoader
from features import NFRIFeatureEngineer
from config import Config

logger = logging.getLogger(__name__)

# Initialize Sentry
try:
    sentry_sdk.init(
        dsn=os.getenv('SENTRY_DSN'),
        environment=os.getenv('ENV', 'development'),
        traces_sample_rate=0.1,
    )
except Exception as e:
    logger.warning(f"Sentry initialization failed: {e}")


class NFRIModelTrainer:
    """Train and evaluate NRFI/YRFI prediction models."""
    
    def __init__(self, config: Config = None):
        """Initialize trainer.
        
        Args:
            config: Configuration object
        """
        self.config = config or Config()
        self.sf = SnowflakeLoader()
        self.feature_engineer = NFRIFeatureEngineer(self.sf)
        self.model = None
        self.calibrated_model = None
        self.feature_names = []
        
    def load_training_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Load historical games with outcomes from Snowflake.
        
        Args:
            start_date: Start date for training data (YYYY-MM-DD)
            end_date: End date for training data (YYYY-MM-DD)
            
        Returns:
            DataFrame with features and target (nrfi)
        """
        logger.info(f"Loading training data from {start_date} to {end_date}")
        
        # Query historical games with first-inning results
        query = """
        SELECT 
            game_id,
            game_date,
            away_team,
            home_team,
            away_pitcher_id,
            home_pitcher_id,
            venue_id,
            temperature,
            wind_speed,
            is_dome,
            away_first_inning_runs,
            home_first_inning_runs,
            CASE WHEN (away_first_inning_runs + home_first_inning_runs) = 0 
                 THEN 1 ELSE 0 END as nrfi
        FROM nrfi_db.features.games_with_outcomes
        WHERE game_date >= %s
          AND game_date <= %s
        ORDER BY game_date
        """
        
        try:
            games_df = pd.DataFrame(
                self.sf.execute_query(query, [start_date, end_date])
            )
            logger.info(f"Loaded {len(games_df)} games")
            return games_df
        except Exception as e:
            logger.error(f"Error loading training data: {e}")
            sentry_sdk.capture_exception(e)
            raise
    
    def prepare_features(self, games_df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Generate features for all games.
        
        Args:
            games_df: DataFrame of games with metadata
            
        Returns:
            Tuple of (X features, y targets)
        """
        logger.info(f"Generating features for {len(games_df)} games")
        
        feature_list = []
        targets = []
        
        for idx, game in games_df.iterrows():
            try:
                game_data = game.to_dict()
                features = self.feature_engineer.generate_game_features(game_data)
                
                # Store feature names from first game
                if idx == 0:
                    self.feature_names = sorted(features.keys())
                
                # Convert to ordered array
                feature_vector = [features.get(fname, 0) for fname in self.feature_names]
                feature_list.append(feature_vector)
                targets.append(game['nrfi'])
                
            except Exception as e:
                logger.warning(f"Error generating features for game {game['game_id']}: {e}")
                sentry_sdk.capture_exception(e)
                continue
        
        X = np.array(feature_list)
        y = np.array(targets)
        
        logger.info(f"Generated {X.shape[1]} features for {len(X)} games")
        logger.info(f"NRFI rate: {y.mean():.3f}")
        
        return X, y
    
    def train_model(self, X: np.ndarray, y: np.ndarray, 
                   cv_splits: int = 5) -> Dict:
        """Train LightGBM model with time-series CV.
        
        Args:
            X: Feature matrix
            y: Target vector
            cv_splits: Number of CV folds
            
        Returns:
            Dict of evaluation metrics
        """
        logger.info(f"Training LightGBM model with {cv_splits}-fold CV")
        
        # LightGBM parameters
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'max_depth': 6,
            'min_child_samples': 20,
            'verbose': -1,
        }
        
        # Time series cross-validation
        tscv = TimeSeriesSplit(n_splits=cv_splits)
        
        cv_scores = {
            'brier': [],
            'auc': [],
            'log_loss': [],
        }
        
        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            logger.info(f"Training fold {fold + 1}/{cv_splits}")
            
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]
            
            # Create LightGBM datasets
            train_data = lgb.Dataset(X_train, label=y_train, feature_name=self.feature_names)
            val_data = lgb.Dataset(X_val, label=y_val, feature_name=self.feature_names, reference=train_data)
            
            # Train model
            model = lgb.train(
                params,
                train_data,
                num_boost_round=500,
                valid_sets=[train_data, val_data],
                valid_names=['train', 'val'],
                callbacks=[
                    lgb.early_stopping(stopping_rounds=50),
                    lgb.log_evaluation(period=100)
                ]
            )
            
            # Evaluate
            y_pred_proba = model.predict(X_val, num_iteration=model.best_iteration)
            
            cv_scores['brier'].append(brier_score_loss(y_val, y_pred_proba))
            cv_scores['auc'].append(roc_auc_score(y_val, y_pred_proba))
            cv_scores['log_loss'].append(log_loss(y_val, y_pred_proba))
        
        # Calculate mean scores
        metrics = {
            'cv_brier_mean': np.mean(cv_scores['brier']),
            'cv_brier_std': np.std(cv_scores['brier']),
            'cv_auc_mean': np.mean(cv_scores['auc']),
            'cv_auc_std': np.std(cv_scores['auc']),
            'cv_logloss_mean': np.mean(cv_scores['log_loss']),
            'cv_logloss_std': np.std(cv_scores['log_loss']),
        }
        
        logger.info(f"CV Metrics: Brier={metrics['cv_brier_mean']:.4f}, "
                   f"AUC={metrics['cv_auc_mean']:.4f}, "
                   f"LogLoss={metrics['cv_logloss_mean']:.4f}")
        
        # Train final model on all data
        logger.info("Training final model on full dataset")
        full_train_data = lgb.Dataset(X, label=y, feature_name=self.feature_names)
        
        self.model = lgb.train(
            params,
            full_train_data,
            num_boost_round=500,
        )
        
        return metrics
    
    def calibrate_model(self, X: np.ndarray, y: np.ndarray, method: str = 'isotonic'):
        """Calibrate model probabilities.
        
        Args:
            X: Feature matrix
            y: Target vector
            method: Calibration method ('isotonic' or 'sigmoid')
        """
        logger.info(f"Calibrating model using {method} method")
        
        class LGBMWrapper:
            """Wrapper for LightGBM to work with CalibratedClassifierCV."""
            def __init__(self, model):
                self.model = model
            
            def predict_proba(self, X):
                preds = self.model.predict(X)
                return np.vstack([1 - preds, preds]).T
        
        wrapped_model = LGBMWrapper(self.model)
        
        self.calibrated_model = CalibratedClassifierCV(
            wrapped_model,
            method=method,
            cv='prefit'
        )
        
        self.calibrated_model.fit(X, y)
        logger.info("Model calibration complete")
    
    def get_feature_importance(self, top_n: int = 20) -> Dict:
        """Get top feature importances.
        
        Args:
            top_n: Number of top features to return
            
        Returns:
            Dict of feature names and importances
        """
        if self.model is None:
            return {}
        
        importance = self.model.feature_importance(importance_type='gain')
        feature_imp = pd.DataFrame({
            'feature': self.feature_names,
            'importance': importance
        }).sort_values('importance', ascending=False).head(top_n)
        
        return dict(zip(feature_imp['feature'], feature_imp['importance'].tolist()))
    
    def save_model(self, model_dir: str, version: str = None):
        """Save model and metadata.
        
        Args:
            model_dir: Directory to save model
            version: Model version string (default: timestamp)
        """
        if version is None:
            version = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        os.makedirs(model_dir, exist_ok=True)
        
        # Save LightGBM model
        model_path = os.path.join(model_dir, f'nrfi_model_{version}.txt')
        self.model.save_model(model_path)
        logger.info(f"Saved LightGBM model to {model_path}")
        
        # Save calibrated model
        if self.calibrated_model:
            calibrated_path = os.path.join(model_dir, f'nrfi_calibrated_{version}.pkl')
            joblib.dump(self.calibrated_model, calibrated_path)
            logger.info(f"Saved calibrated model to {calibrated_path}")
        
        # Save feature names
        features_path = os.path.join(model_dir, f'feature_names_{version}.json')
        with open(features_path, 'w') as f:
            json.dump(self.feature_names, f)
        
        # Save feature importance
        importance = self.get_feature_importance(top_n=50)
        importance_path = os.path.join(model_dir, f'feature_importance_{version}.json')
        with open(importance_path, 'w') as f:
            json.dump(importance, f, indent=2)
        
        logger.info(f"Model version {version} saved successfully")
        
        return version
    
    def load_model(self, model_dir: str, version: str):
        """Load saved model.
        
        Args:
            model_dir: Directory containing model
            version: Model version to load
        """
        model_path = os.path.join(model_dir, f'nrfi_model_{version}.txt')
        self.model = lgb.Booster(model_file=model_path)
        
        calibrated_path = os.path.join(model_dir, f'nrfi_calibrated_{version}.pkl')
        if os.path.exists(calibrated_path):
            self.calibrated_model = joblib.load(calibrated_path)
        
        features_path = os.path.join(model_dir, f'feature_names_{version}.json')
        with open(features_path, 'r') as f:
            self.feature_names = json.load(f)
        
        logger.info(f"Loaded model version {version}")


def main():
    """Main training pipeline."""
    # Training configuration
    end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365*3)).strftime('%Y-%m-%d')  # 3 years
    
    logger.info(f"Starting NRFI model training pipeline")
    logger.info(f"Training period: {start_date} to {end_date}")
    
    try:
        # Initialize trainer
        trainer = NFRIModelTrainer()
        
        # Load data
        games_df = trainer.load_training_data(start_date, end_date)
        
        # Generate features
        X, y = trainer.prepare_features(games_df)
        
        # Train model
        metrics = trainer.train_model(X, y, cv_splits=5)
        
        # Calibrate
        trainer.calibrate_model(X, y, method='isotonic')
        
        # Save model
        version = trainer.save_model('/tmp/models')
        
        logger.info(f"Training complete. Model version: {version}")
        logger.info(f"Metrics: {json.dumps(metrics, indent=2)}")
        
        # Log to PostHog (if configured)
        try:
            import posthog
            if os.getenv('POSTHOG_API_KEY'):
                posthog.capture(
                    'nrfi_model_trained',
                    {
                        'version': version,
                        'metrics': metrics,
                        'num_games': len(games_df),
                        'num_features': X.shape[1],
                    }
                )
        except Exception as e:
            logger.warning(f"PostHog logging failed: {e}")
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        sentry_sdk.capture_exception(e)
        raise


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    main()

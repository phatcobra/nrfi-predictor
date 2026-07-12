"""REST API for NRFI/YRFI predictions.

FastAPI-based API for serving predictions, deployed on AWS Lambda + API Gateway.
Endpoints:
- GET /predictions/today - Get today's predictions
- GET /predictions/{date} - Get predictions for specific date
- GET /predictions/{game_id} - Get prediction for specific game
- GET /health - Health check
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from datetime import datetime, timedelta
from typing import List, Optional
import logging
import os
import sentry_sdk
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from snowflake_loader import SnowflakeLoader
from predict_daily import NFRIDailyPredictor

logger = logging.getLogger(__name__)

# Initialize Sentry
try:
    sentry_sdk.init(
        dsn=os.getenv('SENTRY_DSN'),
        environment=os.getenv('ENV', 'production'),
        traces_sample_rate=0.1,
    )
except Exception as e:
    logger.warning(f"Sentry initialization failed: {e}")

# Create FastAPI app
app = FastAPI(
    title="NRFI/YRFI Prediction API",
    description="MLB First Inning Run predictions (NRFI/YRFI)",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Sentry middleware
if os.getenv('SENTRY_DSN'):
    app.add_middleware(SentryAsgiMiddleware)

# Initialize Snowflake loader
sf = SnowflakeLoader()


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "NRFI/YRFI Prediction API",
        "version": "1.0.0",
        "status": "active",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Test Snowflake connection
        result = sf.execute_query("SELECT 1")
        db_status = "healthy" if result else "unhealthy"
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        db_status = "unhealthy"
    
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/predictions/today")
async def get_todays_predictions(
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum confidence threshold")
):
    """Get predictions for today's games.
    
    Args:
        min_confidence: Optional minimum confidence filter (0-1)
    
    Returns:
        List of predictions for today
    """
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Query from Snowflake
        query = """
        SELECT *
        FROM nrfi_db.predictions.daily_predictions
        WHERE game_date = %s
        ORDER BY confidence DESC
        """
        
        results = sf.execute_query(query, [today])
        
        if not results:
            return {
                "date": today,
                "predictions": [],
                "message": "No predictions available for today"
            }
        
        predictions = results
        
        # Apply confidence filter if specified
        if min_confidence is not None:
            predictions = [p for p in predictions if p.get('confidence', 0) >= min_confidence]
        
        return {
            "date": today,
            "count": len(predictions),
            "predictions": predictions,
        }
        
    except Exception as e:
        logger.error(f"Error fetching today's predictions: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/predictions/date/{date}")
async def get_predictions_by_date(
    date: str,
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0)
):
    """Get predictions for a specific date.
    
    Args:
        date: Date in YYYY-MM-DD format
        min_confidence: Optional minimum confidence filter
    
    Returns:
        List of predictions for the date
    """
    try:
        # Validate date format
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        query = """
        SELECT *
        FROM nrfi_db.predictions.daily_predictions
        WHERE game_date = %s
        ORDER BY confidence DESC
        """
        
        results = sf.execute_query(query, [date])
        
        if not results:
            return {
                "date": date,
                "predictions": [],
                "message": f"No predictions found for {date}"
            }
        
        predictions = results
        
        if min_confidence is not None:
            predictions = [p for p in predictions if p.get('confidence', 0) >= min_confidence]
        
        return {
            "date": date,
            "count": len(predictions),
            "predictions": predictions,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching predictions for {date}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/predictions/game/{game_id}")
async def get_prediction_by_game(
    game_id: str
):
    """Get prediction for a specific game.
    
    Args:
        game_id: Game identifier
    
    Returns:
        Prediction for the game
    """
    try:
        query = """
        SELECT *
        FROM nrfi_db.predictions.daily_predictions
        WHERE game_id = %s
        ORDER BY prediction_timestamp DESC
        LIMIT 1
        """
        
        results = sf.execute_query(query, [game_id])
        
        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"No prediction found for game {game_id}"
            )
        
        return results[0]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching prediction for game {game_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/predictions/top")
async def get_top_picks(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format, defaults to today"),
    limit: int = Query(5, ge=1, le=20, description="Number of top picks to return")
):
    """Get top prediction picks based on confidence.
    
    Args:
        date: Optional date filter (defaults to today)
        limit: Number of picks to return (1-20)
    
    Returns:
        Top prediction picks
    """
    try:
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        else:
            try:
                datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        query = f"""
        SELECT *
        FROM nrfi_db.predictions.daily_predictions
        WHERE game_date = %s
          AND recommendation IN ('NRFI', 'YRFI')
        ORDER BY confidence DESC
        LIMIT {limit}
        """
        
        results = sf.execute_query(query, [date])
        
        return {
            "date": date,
            "top_picks": results,
            "count": len(results)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching top picks: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats/performance")
async def get_performance_stats(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)")
):
    """Get historical prediction performance statistics.
    
    Args:
        start_date: Optional start date filter
        end_date: Optional end date filter
    
    Returns:
        Performance metrics
    """
    try:
        # Default to last 30 days if not specified
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        query = """
        SELECT 
            COUNT(*) as total_predictions,
            AVG(confidence) as avg_confidence,
            SUM(CASE WHEN recommendation = 'NRFI' THEN 1 ELSE 0 END) as nrfi_count,
            SUM(CASE WHEN recommendation = 'YRFI' THEN 1 ELSE 0 END) as yrfi_count,
            SUM(CASE WHEN recommendation = 'PASS' THEN 1 ELSE 0 END) as pass_count
        FROM nrfi_db.predictions.daily_predictions
        WHERE game_date >= %s
          AND game_date <= %s
        """
        
        results = sf.execute_query(query, [start_date, end_date])
        
        if not results or not results[0]:
            return {
                "start_date": start_date,
                "end_date": end_date,
                "stats": {},
                "message": "No data available for this period"
            }
        
        stats = results[0]
        
        return {
            "start_date": start_date,
            "end_date": end_date,
            "stats": stats
        }
        
    except Exception as e:
        logger.error(f"Error fetching performance stats: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predictions/generate")
async def generate_predictions(
    date: Optional[str] = Query(None, description="Date to generate predictions for (YYYY-MM-DD)")
):
    """Trigger prediction generation for a specific date.
    
    This endpoint triggers the prediction pipeline to generate fresh predictions.
    Typically called by scheduled jobs, but can be manually triggered.
    
    Args:
        date: Optional date (defaults to today)
    
    Returns:
        Status of prediction generation
    """
    try:
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        # Initialize predictor
        predictor = NFRIDailyPredictor()
        
        # Get games
        games = predictor.get_todays_games(date)
        
        if not games:
            return {
                "status": "no_games",
                "message": f"No games scheduled for {date}",
                "date": date
            }
        
        # Generate predictions
        predictions = predictor.generate_predictions(games)
        
        # Save to Snowflake
        predictor.save_predictions(predictions)
        
        return {
            "status": "success",
            "date": date,
            "predictions_generated": len(predictions),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error generating predictions: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=str(e))


# AWS Lambda handler
handler = Mangum(app)


if __name__ == "__main__":
    # For local development
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

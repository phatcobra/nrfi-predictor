#!/usr/bin/env python3
"""Standalone NRFI/YRFI Prediction Web App

Runs locally with free MLB data, no cloud services required.
Access at http://localhost:5000
"""

from flask import Flask, render_template, jsonify
import statsapi
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import lightgbm as lgb
import pickle
import os

app = Flask(__name__)

# Database setup
DB_PATH = 'nrfi_data.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            game_date TEXT,
            away_team TEXT,
            home_team TEXT,
            away_pitcher TEXT,
            home_pitcher TEXT,
            away_first_runs INTEGER,
            home_first_runs INTEGER,
            nrfi INTEGER
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            game_id TEXT PRIMARY KEY,
            game_date TEXT,
            away_team TEXT,
            home_team TEXT,
            nrfi_prob REAL,
            prediction TEXT,
            timestamp TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def fetch_todays_games():
    """Fetch today's MLB games using free MLB Stats API"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    try:
        schedule = statsapi.schedule(date=today)
        games = []
        
        for game in schedule:
            games.append({
                'game_id': str(game['game_id']),
                'game_date': game['game_date'],
                'game_time': game.get('game_time', 'TBD'),
                'away_team': game['away_name'],
                'home_team': game['home_name'],
                'away_pitcher': game.get('away_probable_pitcher', 'TBD'),
                'home_pitcher': game.get('home_probable_pitcher', 'TBD'),
                'status': game.get('status', 'Scheduled')
            })
        
        return games
    except Exception as e:
        print(f"Error fetching games: {e}")
        return []

def get_pitcher_stats(pitcher_name, lookback_days=365):
    """Get basic pitcher stats"""
    # Simplified - in production would query actual data
    # For demo, return baseline values
    return {
        'era': 4.0,
        'whip': 1.25,
        'k_per_9': 8.5,
        'first_inning_era': 4.2,
        'nrfi_rate': 0.65
    }

def get_team_stats(team_name):
    """Get basic team offensive stats"""
    # Simplified baseline
    return {
        'batting_avg': 0.245,
        'obp': 0.315,
        'slg': 0.410,
        'first_inning_runs_per_game': 0.35
    }

def generate_features(game):
    """Generate basic features for prediction"""
    away_p_stats = get_pitcher_stats(game['away_pitcher'])
    home_p_stats = get_pitcher_stats(game['home_pitcher'])
    away_t_stats = get_team_stats(game['away_team'])
    home_t_stats = get_team_stats(game['home_team'])
    
    features = {
        'away_p_era': away_p_stats['era'],
        'away_p_whip': away_p_stats['whip'],
        'away_p_nrfi_rate': away_p_stats['nrfi_rate'],
        'home_p_era': home_p_stats['era'],
        'home_p_whip': home_p_stats['whip'],
        'home_p_nrfi_rate': home_p_stats['nrfi_rate'],
        'away_t_obp': away_t_stats['obp'],
        'away_t_slg': away_t_stats['slg'],
        'home_t_obp': home_t_stats['obp'],
        'home_t_slg': home_t_stats['slg'],
    }
    
    return features

def simple_nrfi_model(features):
    """Simple rule-based model (placeholder for ML model)"""
    # Weighted scoring
    away_p_score = (1 / features['away_p_era']) * 10 * features['away_p_nrfi_rate']
    home_p_score = (1 / features['home_p_era']) * 10 * features['home_p_nrfi_rate']
    
    away_o_score = (features['away_t_obp'] + features['away_t_slg']) / 2
    home_o_score = (features['home_t_obp'] + features['home_t_slg']) / 2
    
    pitcher_strength = (away_p_score + home_p_score) / 2
    offense_strength = (away_o_score + home_o_score) / 2
    
    # NRFI probability based on pitcher strength vs offense
    nrfi_prob = 0.5 + (pitcher_strength - offense_strength) * 0.3
    nrfi_prob = max(0.2, min(0.9, nrfi_prob))  # Clamp between 20-90%
    
    return nrfi_prob

def predict_game(game):
    """Generate NRFI prediction for a game"""
    features = generate_features(game)
    nrfi_prob = simple_nrfi_model(features)
    
    if nrfi_prob >= 0.60:
        prediction = 'NRFI'
        confidence = nrfi_prob
    elif nrfi_prob <= 0.40:
        prediction = 'YRFI'
        confidence = 1 - nrfi_prob
    else:
        prediction = 'PASS'
        confidence = 0.5
    
    return {
        'game_id': game['game_id'],
        'game_date': game['game_date'],
        'game_time': game['game_time'],
        'away_team': game['away_team'],
        'home_team': game['home_team'],
        'away_pitcher': game['away_pitcher'],
        'home_pitcher': game['home_pitcher'],
        'nrfi_probability': round(nrfi_prob, 3),
        'yrfi_probability': round(1 - nrfi_prob, 3),
        'prediction': prediction,
        'confidence': round(confidence, 3),
        'status': game.get('status', 'Scheduled')
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/predictions/today')
def get_todays_predictions():
    games = fetch_todays_games()
    predictions = [predict_game(game) for game in games]
    
    # Sort by confidence
    predictions.sort(key=lambda x: x['confidence'], reverse=True)
    
    return jsonify({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'count': len(predictions),
        'predictions': predictions
    })

@app.route('/api/stats')
def get_stats():
    # Placeholder stats
    return jsonify({
        'total_predictions': 0,
        'accuracy': 0.0,
        'nrfi_rate': 0.68,
        'avg_confidence': 0.65
    })

if __name__ == '__main__':
    init_db()
    print("\n" + "="*50)
    print("NRFI/YRFI Predictor - Local Server")
    print("="*50)
    print("\nAccess the app at: http://localhost:5000")
    print("\nPress CTRL+C to stop\n")
    app.run(debug=True, host='0.0.0.0', port=5000)

# Assets Directory

This directory contains all the visual assets referenced in the main README.md file of the Yelp Data Analysis Project.

## Directory Structure

```
assets/
├── images/          # Static images and charts
└── animations/      # Animated GIFs and video content
```

## Images Directory (`/images/`)

Contains static chart images and visualizations:

### Data Schema & Distribution Charts
- `dataset_schema.png` - Entity relationships and schema overview of Yelp datasets
- `rating_distribution.png` - Distribution of Yelp business ratings (1.0–5.0)
- `top_categories.png` - Top 20 most common business categories on Yelp

### Geographic Analysis
- `global_distribution.png` - Global distribution of Yelp businesses
- `north_america.png` - Zoomed-in view: North America
- `europe.png` - Zoomed-in view: Europe
- `city_density_maps.png` - Business density patterns across Las Vegas, Phoenix, Stuttgart, and Edinburgh

### User Behavior Analysis
- `review_volume_distribution.png` - Distribution of number of reviews per user and cumulative distribution
- `useful_vs_rating.png` - Trend of max/avg rating, review length, and review count vs. useful threshold
- `elite_vs_regular_sentiment.png` - Sentiment score distribution of reviews by elite vs. regular users
- `word_clouds.png` - Word cloud analysis of positive and negative reviews

### Network Analysis
- `friendship_network.png` - Sampled Yelp user friendship network (Spring layout)
- `stuttgart_network.png` - Stuttgart user network - Spring layout with Louvain communities

## Animations Directory (`/animations/`)

Contains animated visualizations:

- `1.gif` - Animated heatmap of business ratings by location (Las Vegas)
- `2.gif` - Heatmap animation of top user's review locations across time
- `yelp_10.gif` - Additional animation file (moved from root directory)

## Usage

All images are referenced in the main README.md using relative paths:
- Static images: `assets/images/filename.png`
- Animations: `assets/animations/filename.gif`

## Notes

- All placeholder files are currently empty (0 bytes) and should be replaced with actual generated visualizations
- The original GitHub URLs have been replaced with local paths in the main README.md
- Images should maintain the specified dimensions for consistent display in the documentation
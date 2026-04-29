import os

BQ_PROJECT = os.environ.get("BQ_PROJECT")
BQ_DATASET = os.environ.get("BQ_DATASET")

TABLE_COMMITS = f"{BQ_PROJECT}.{BQ_DATASET}.github_commit_history"
TABLE_TICKETS = f"{BQ_PROJECT}.{BQ_DATASET}.jira_tickets"
TABLE_OWNERSHIP = f"{BQ_PROJECT}.{BQ_DATASET}.ownership_map"
TABLE_MEMBERS = f"{BQ_PROJECT}.{BQ_DATASET}.team_members"
TABLE_MEMBER_REPOS = f"{BQ_PROJECT}.{BQ_DATASET}.team_members_repositories"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DEFAULT_REPO = os.environ.get("DEFAULT_REPO", "")

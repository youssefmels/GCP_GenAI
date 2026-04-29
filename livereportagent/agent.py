from google.adk.agents.llm_agent import Agent
from google.adk.tools.bigquery import BigQueryToolset
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StdioConnectionParams as McpStdioConnectionParams,
)
from google.cloud import bigquery
from mcp import StdioServerParameters
import json
import os
import requests

from livereportagent.config import (
    TABLE_COMMITS, TABLE_TICKETS, TABLE_OWNERSHIP, TABLE_MEMBERS,
    TABLE_MEMBER_REPOS, GITHUB_TOKEN,
)

# --- Tool definitions ---

bigquery_toolset = BigQueryToolset()

# To use the official GitHub MCP server (100+ tools, requires Docker):
# github_mcp_toolset = McpToolset(
#     connection_params=McpStdioConnectionParams(
#         server_params=StdioServerParameters(
#             command='docker',
#             args=[
#                 'run', '-i', '--rm',
#                 '-e', 'GITHUB_PERSONAL_ACCESS_TOKEN',
#                 'ghcr.io/github/github-mcp-server',
#             ],
#             env={"GITHUB_PERSONAL_ACCESS_TOKEN": GITHUB_TOKEN},
#         ),
#         timeout=30,
#     ),
# )

github_mcp_toolset = McpToolset(
    connection_params=McpStdioConnectionParams(
        server_params=StdioServerParameters(
            command='npx',
            args=['-y', '@modelcontextprotocol/server-github'],
            env={"GITHUB_TOKEN": GITHUB_TOKEN},
        ),
        timeout=30,
    ),
)

atlassian_mcp_toolset = McpToolset(
    connection_params=McpStdioConnectionParams(
        server_params=StdioServerParameters(
            command='npx',
            args=['-y', 'mcp-remote', 'https://mcp.atlassian.com/v1/mcp'],
        ),
        timeout=30,
    ),
)

bq_client = bigquery.Client()


def get_commit_details(repo: str, commit_sha: str) -> str:
    """Fetches detailed information about a specific GitHub commit including
    files changed, additions, deletions, and patch diffs.

    Args:
        repo: Repository in 'owner/repo' format (e.g. 'youssefmels/gcp_test_repo').
        commit_sha: The full or short SHA of the commit.

    Returns:
        JSON string with commit details: author, message, files changed
        (with filename, status, additions, deletions, and patch), and
        a summary of modules affected.
    """
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    resp = requests.get(
        f"https://api.github.com/repos/{repo}/commits/{commit_sha}",
        headers=headers,
        timeout=15,
    )
    if resp.status_code != 200:
        return json.dumps({"error": f"GitHub API returned {resp.status_code}: {resp.text[:200]}"})

    data = resp.json()
    files = []
    modules = set()
    for f in data.get("files", []):
        top_dir = f["filename"].split("/")[0] if "/" in f["filename"] else f["filename"]
        modules.add(top_dir)
        files.append({
            "filename": f["filename"],
            "status": f.get("status", "unknown"),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            "patch": f.get("patch", "")[:500],
        })

    result = {
        "commit_sha": data["sha"],
        "author": data.get("author", {}).get("login", data["commit"]["author"]["name"]),
        "message": data["commit"]["message"],
        "timestamp": data["commit"]["author"]["date"],
        "files_changed_count": len(files),
        "modules_affected": ", ".join(sorted(modules)),
        "files": files,
        "stats": data.get("stats", {}),
    }
    return json.dumps(result, indent=2)


def get_stale_tickets(days_threshold: int = 7, module: str = "") -> str:
    """Finds JIRA tickets that have not been updated for a given number of days.

    Args:
        days_threshold: Number of days since last update to consider stale.
            Defaults to 7.
        module: Optional module name to filter by. If empty, returns all
            stale tickets across all modules.

    Returns:
        JSON array of stale tickets with ticket_id, title, status,
        assignee, module, and days since last update.
    """
    module_filter = ""
    params = [bigquery.ScalarQueryParameter("days", "INT64", days_threshold)]
    if module:
        module_filter = "AND LOWER(module) LIKE CONCAT('%', LOWER(@mod), '%')"
        params.append(bigquery.ScalarQueryParameter("mod", "STRING", module))

    query = f"""
        SELECT ticket_id, title, status, assignee, module, updated_at,
               TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), CAST(updated_at AS TIMESTAMP), DAY) AS days_stale
        FROM `{TABLE_TICKETS}`
        WHERE status != 'Done'
          AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), CAST(updated_at AS TIMESTAMP), DAY) >= @days
          {module_filter}
        ORDER BY days_stale DESC
        LIMIT 20
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    results = bq_client.query(query, job_config=job_config).result()

    tickets = []
    for row in results:
        tickets.append({
            "ticket_id": row.ticket_id,
            "title": row.title,
            "status": row.status,
            "assignee": row.assignee,
            "module": row.module,
            "updated_at": row.updated_at,
            "days_stale": row.days_stale,
        })

    if not tickets:
        return f"No stale tickets found (threshold: {days_threshold} days)."
    return json.dumps(tickets, indent=2)


def correlate_commits_to_tickets(module: str = "") -> str:
    """Cross-references GitHub commits with JIRA tickets by extracting ticket
    IDs from commit messages (e.g. 'KAN-3' in 'feat: add feature (KAN-3)').

    Args:
        module: Optional module name to filter commits by. If empty,
            checks all recent commits.

    Returns:
        JSON with two lists: tickets_with_commits (active development)
        and tickets_without_commits (potentially stalled).
    """
    module_filter = ""
    params = []
    if module:
        module_filter = "WHERE LOWER(modules_affected) LIKE CONCAT('%', LOWER(@mod), '%')"
        params.append(bigquery.ScalarQueryParameter("mod", "STRING", module))

    query = f"""
        WITH recent_commits AS (
            SELECT commit_id, author, commit_message, modules_affected, timestamp
            FROM `{TABLE_COMMITS}`
            {module_filter}
            ORDER BY timestamp DESC
            LIMIT 50
        ),
        open_tickets AS (
            SELECT ticket_id, title, status, assignee, module
            FROM `{TABLE_TICKETS}`
            WHERE status != 'Done'
        )
        SELECT
            t.ticket_id, t.title, t.status, t.assignee, t.module,
            c.commit_id, c.author AS commit_author, c.commit_message, c.timestamp AS commit_time
        FROM open_tickets t
        LEFT JOIN recent_commits c
            ON c.commit_message LIKE CONCAT('%', t.ticket_id, '%')
        ORDER BY t.ticket_id
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    results = list(bq_client.query(query, job_config=job_config).result())

    with_commits = {}
    without_commits = []

    for row in results:
        tid = row.ticket_id
        if row.commit_id:
            if tid not in with_commits:
                with_commits[tid] = {
                    "ticket_id": tid, "title": row.title,
                    "status": row.status, "assignee": row.assignee,
                    "commits": [],
                }
            with_commits[tid]["commits"].append({
                "commit_id": row.commit_id,
                "author": row.commit_author,
                "message": row.commit_message,
                "time": row.commit_time,
            })
        elif tid not in with_commits:
            without_commits.append({
                "ticket_id": tid, "title": row.title,
                "status": row.status, "assignee": row.assignee,
                "module": row.module,
            })

    return json.dumps({
        "tickets_with_commits": list(with_commits.values()),
        "tickets_without_commits": without_commits,
    }, indent=2, default=str)


def insert_github_commits(commits_json: str) -> str:
    """Inserts GitHub commit records into the github_commit_history BigQuery table.

    The agent should first use the GitHub MCP tools to fetch commit data from a
    repository, then call this tool with the results formatted as a JSON array.

    Args:
        commits_json: A JSON array of commit objects. Each object must have:
            - commit_id (str): The full SHA of the commit.
            - author (str): The username or name of the commit author.
            - commit_message (str): The commit message text.
            - files_changed_count (int): Number of files changed in the commit.
            - modules_affected (str): Comma-separated list of modules/directories touched.
            - timestamp (str): ISO 8601 timestamp of the commit (e.g. "2026-04-20T14:30:00Z").

    Returns:
        A summary of how many rows were inserted or any errors encountered.
    """
    try:
        rows = json.loads(commits_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"
    if not isinstance(rows, list):
        return "Expected a JSON array of commit objects."
    if not rows:
        return "No commits provided to insert."

    required = {"commit_id", "author", "commit_message", "files_changed_count", "modules_affected", "timestamp"}
    for i, row in enumerate(rows):
        missing = required - set(row.keys())
        if missing:
            return f"Row {i} is missing required fields: {missing}"

    incoming_ids = [r["commit_id"] for r in rows]
    placeholders = ", ".join(f"'{cid}'" for cid in incoming_ids)
    dedup_query = f"SELECT commit_id FROM `{TABLE_COMMITS}` WHERE commit_id IN ({placeholders})"
    existing = {row.commit_id for row in bq_client.query(dedup_query).result()}

    new_rows = [r for r in rows if r["commit_id"] not in existing]
    if not new_rows:
        return f"All {len(rows)} commit(s) already exist in BigQuery. Nothing to insert."

    errors = bq_client.insert_rows_json(TABLE_COMMITS, new_rows)
    if errors:
        return f"Encountered errors inserting rows: {errors}"
    skipped = len(rows) - len(new_rows)
    msg = f"Successfully inserted {len(new_rows)} new commit(s) into github_commit_history."
    if skipped:
        msg += f" Skipped {skipped} duplicate(s)."
    return msg


def insert_jira_tickets(tickets_json: str) -> str:
    """Inserts JIRA ticket records into the jira_tickets BigQuery table.

    The agent should first use the Atlassian MCP tools to fetch ticket data from
    JIRA, then call this tool with the results formatted as a JSON array.

    Args:
        tickets_json: A JSON array of ticket objects. Each object must have:
            - ticket_id (str): The JIRA ticket ID (e.g. "AUTH-1234").
            - title (str): The ticket summary/title.
            - description (str): The ticket description.
            - status (str): Current status (e.g. "In Progress", "To Do", "Done").
            - assignee (str): Username of the person assigned.
            - module (str): The module or component the ticket belongs to.
            - dependencies (str): Comma-separated list of linked/blocking ticket IDs.
            - created_at (str): ISO 8601 timestamp of creation.
            - updated_at (str): ISO 8601 timestamp of last update.

    Returns:
        A summary of how many rows were inserted or any errors encountered.
    """
    try:
        rows = json.loads(tickets_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"
    if not isinstance(rows, list):
        return "Expected a JSON array of ticket objects."
    if not rows:
        return "No tickets provided to insert."

    required = {"ticket_id", "title", "description", "status", "assignee", "module", "dependencies", "created_at", "updated_at"}
    for i, row in enumerate(rows):
        missing = required - set(row.keys())
        if missing:
            return f"Row {i} is missing required fields: {missing}"

    incoming_ids = [r["ticket_id"] for r in rows]
    placeholders = ", ".join(f"'{tid}'" for tid in incoming_ids)
    dedup_query = f"SELECT ticket_id FROM `{TABLE_TICKETS}` WHERE ticket_id IN ({placeholders})"
    existing = {row.ticket_id for row in bq_client.query(dedup_query).result()}

    new_rows = [r for r in rows if r["ticket_id"] not in existing]
    if not new_rows:
        return f"All {len(rows)} ticket(s) already exist in BigQuery. Nothing to insert."

    errors = bq_client.insert_rows_json(TABLE_TICKETS, new_rows)
    if errors:
        return f"Encountered errors inserting rows: {errors}"
    skipped = len(rows) - len(new_rows)
    msg = f"Successfully inserted {len(new_rows)} new ticket(s) into jira_tickets."
    if skipped:
        msg += f" Skipped {skipped} duplicate(s)."
    return msg


def lookup_ownership(module_or_ticket: str) -> dict:
    """Queries BigQuery to find the responsible person for a module or ticket.

    Joins the ownership_map and team_members tables to return the owner's
    full name, email, and role. Falls back to fallback_owner if the primary
    owner is not found in team_members.

    Args:
        module_or_ticket: The module name or JIRA ticket identifier
            to look up (e.g. "auth-service", "payments", "PAY-1234").

    Returns:
        A dict with owner details (name, email, role) and fallback info.
    """
    query = f"""
        SELECT
            o.module,
            o.owner,
            o.fallback_owner,
            t.full_name,
            t.email,
            t.role,
            t.level
        FROM `{TABLE_OWNERSHIP}` o
        LEFT JOIN `{TABLE_MEMBERS}` t ON o.owner = t.username
        WHERE LOWER(o.module) LIKE CONCAT('%', LOWER(@search_term), '%')
           OR LOWER(@search_term) LIKE CONCAT('%', LOWER(o.module), '%')
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("search_term", "STRING", module_or_ticket),
        ]
    )
    results = bq_client.query(query, job_config=job_config).result()
    for row in results:
        return {
            "module_or_ticket": module_or_ticket,
            "matched_module": row.module,
            "owner_username": row.owner,
            "owner_full_name": row.full_name,
            "owner_email": row.email,
            "owner_role": row.role,
            "owner_level": row.level,
            "fallback_owner": row.fallback_owner,
        }
    return {
        "module_or_ticket": module_or_ticket,
        "matched_module": None,
        "owner_username": None,
        "owner_full_name": "UNKNOWN — manual review needed",
        "owner_email": None,
        "owner_role": None,
        "owner_level": None,
        "fallback_owner": None,
    }


def lookup_user_repos(username: str) -> dict:
    """Looks up a team member's profile and their assigned repositories.

    Args:
        username: The GitHub username to look up.
    Returns:
        A dict with the user's profile info and list of accessible repositories.
    """
    result: dict = {"username": username, "found": False, "repositories": []}

    member_query = f"""
        SELECT full_name, email, role, level
        FROM `{TABLE_MEMBERS}`
        WHERE LOWER(username) = LOWER(@uname)
        LIMIT 1
    """
    repo_query = f"""
        SELECT repository FROM `{TABLE_MEMBER_REPOS}`
        WHERE LOWER(username) = LOWER(@uname)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("uname", "STRING", username)]
    )
    try:
        for row in bq_client.query(member_query, job_config=job_config).result():
            result["found"] = True
            result["full_name"] = row.full_name
            result["email"] = row.email
            result["role"] = row.role
            result["level"] = row.level
    except Exception:
        pass

    try:
        result["repositories"] = [
            row.repository for row in bq_client.query(repo_query, job_config=job_config).result()
        ]
    except Exception:
        pass

    return result


# --- Atlassian / JIRA Sync Agent ---

atlassian_agent = Agent(
    model='gemini-2.5-flash',
    name='atlassian_agent',
    description=(
        'Fetches live JIRA ticket data via the Atlassian MCP and inserts '
        'it into the jira_tickets BigQuery table.'
    ),
    instruction="""\
You are the JIRA Sync Agent. Your job is to fetch ticket data from JIRA and store it in BigQuery.

When given a ticket ID, module name, or search keywords:

1. **Fetch tickets from JIRA**
   - Use the Atlassian MCP tools to search for or fetch the relevant JIRA ticket(s).
   - If a ticket ID is provided (e.g. "AUTH-1234"), fetch that ticket directly.
   - If a module or keyword is provided, search JIRA for matching issues.

2. **Format the data as JSON**
   - Build a JSON array where each element is an object with these exact keys:
     - "ticket_id": the JIRA ticket ID (e.g. "AUTH-1234")
     - "title": the ticket summary/title
     - "description": the ticket description text
     - "status": current status (e.g. "In Progress", "To Do", "Done")
     - "assignee": username of the assigned person
     - "module": the module or component the ticket belongs to
     - "dependencies": comma-separated list of linked/blocking ticket IDs, or empty string
     - "created_at": ISO 8601 timestamp (e.g. "2026-04-10T09:00:00Z")
     - "updated_at": ISO 8601 timestamp of last update

3. **Insert into BigQuery**
   - Call the `insert_jira_tickets` tool with the JSON array as a string.
   - Report back how many tickets were synced and any errors.

Also return the fetched ticket details as a summary to the orchestrator so they can be used downstream.""",
    tools=[atlassian_mcp_toolset, insert_jira_tickets],
)

# --- GitHub Sync Agent ---

github_sync_agent = Agent(
    model='gemini-2.5-flash',
    name='github_sync_agent',
    description=(
        'Reads commit history from a GitHub repository via MCP and inserts '
        'the data into the github_commit_history BigQuery table.'
    ),
    instruction="""\
You are the GitHub Sync Agent. Your job is to fetch commit data from GitHub and store it in BigQuery.

When given a repository (owner/repo) and optionally a branch or module path:

1. **List commits**
   - Use the `list_commits` MCP tool to get recent commits for the repository.
   - This returns each commit's SHA, author, message, and timestamp.

2. **Get file-level details when requested**
   - When the user asks about files changed, diffs, or details of a specific commit,
     use the `get_commit_details` tool with the repo and commit SHA.
   - This returns files changed, additions, deletions, patch diffs, and modules affected.
   - Do NOT call it for every commit when doing a bulk sync -- only when specifically asked.

3. **Format the data as JSON for BigQuery sync**
   - Build a JSON array where each element is an object with these exact keys:
     - "commit_id": the full commit SHA
     - "author": the author's GitHub username
     - "commit_message": the first line of the commit message
     - "files_changed_count": number of files changed (integer, use 0 if unknown)
     - "modules_affected": comma-separated list of top-level directories touched (use "" if unknown)
     - "timestamp": ISO 8601 timestamp (e.g. "2026-04-20T14:30:00Z")

4. **Insert into BigQuery**
   - Call the `insert_github_commits` tool with the JSON array as a string.
   - The tool automatically skips duplicates that already exist.
   - Report back how many commits were synced and any skipped.

Always confirm the repository details before fetching. If the repo or branch is ambiguous, ask for clarification.""",
    tools=[github_mcp_toolset, insert_github_commits],
)

# --- Sub-agent 1: Investigator ---

investigator_agent = Agent(
    model='gemini-2.5-flash',
    name='investigator_agent',
    description=(
        'Investigates blocker details by querying BigQuery for JIRA ticket '
        'status and ownership, and checking GitHub commit history on the '
        'relevant module to build a factual picture of the blocker.'
    ),
    instruction="""\
You are the Blocker Investigator. You receive parsed blocker context from the orchestrator \
(developer name, task/module, dependency, and reason for the block).

Your job is to build a **factual picture** of the blocker by performing these steps:

1. **Query BigQuery for JIRA ticket details**
   - Use the BigQuery tools to query the `jira_tickets` table.
   - Search by module name, ticket_id, or keywords from the blocker description.
   - Retrieve: ticket_id, title, status, assignee, module, dependencies, created_at, updated_at.
   - If no exact match, search by module or description keywords and list the closest candidates.

2. **Check GitHub commit history on the relevant module**
   - Use the BigQuery tools to query the `github_commit_history` table.
   - Filter by the module in `modules_affected` to find recent commits.
   - Retrieve: commit_id, author, commit_message, files_changed_count, modules_affected, timestamp.
   - Determine: who last committed, when, how many recent commits exist, and whether the work looks incomplete or abandoned (e.g. no commits in weeks, few files changed).

3. **Look up the ownership map**
   - Use the `lookup_ownership` tool with the module name or ticket identifier.
   - It returns the owner's username, full name, email, role, level, and a fallback_owner.
   - Compare the JIRA assignee and the last GitHub committer to the ownership map result — flag any discrepancies.
   - If the primary owner seems inactive, note the fallback_owner as an alternative contact.

4. **Look up a user's profile and repo access**
   - Use `lookup_user_repos` with a GitHub username to get their profile (name, email, role, level) and which repositories they are assigned to.
   - Use this when asked "what repos does X have access to" or "who is X".

5. **Return your findings** to the orchestrator as a structured summary:
   - JIRA ticket: ticket_id, title, status, assignee, last updated
   - GitHub activity: last committer, last commit date, number of recent commits, completeness signal
   - Ownership: responsible person (name, email, role) from the ownership map, plus fallback_owner
   - Discrepancies or flags (e.g. assignee ≠ owner, no recent commits, ticket stale)

Be factual and concise. Do not speculate — only report what the data shows.""",
    tools=[
        bigquery_toolset, lookup_ownership, lookup_user_repos,
        get_stale_tickets, correlate_commits_to_tickets,
    ],
)

# --- Sub-agent 2: Code Analysis Agent ---

code_analysis_agent = Agent(
    model='gemini-2.5-flash',
    name='code_analysis_agent',
    description=(
        'Analyzes code changes in GitHub repositories: fetches commit diffs, '
        'summarizes what changed, identifies which files and modules were '
        'affected, and checks PR status.'
    ),
    instruction="""\
You are the Code Analysis Agent. You help developers understand what changed in a repository.

When asked about code changes, commits, or PRs:

1. **For commit details and file diffs**:
   - Use `get_commit_details` with the repo and commit SHA to get files changed,
     additions, deletions, and actual code patches.
   - Summarize the changes in plain language: what was added, modified, or deleted.

2. **For recent activity on a module**:
   - Use the GitHub MCP `list_commits` tool to find recent commits.
   - Then use `get_commit_details` on the relevant ones to understand the changes.

3. **For PR information**:
   - Use the GitHub MCP tools to list or search pull requests.
   - Report PR status, review state, and files involved.

4. **For correlating code with tickets**:
   - Use `correlate_commits_to_tickets` to find which tickets have associated commits
     and which ones are missing code activity.

Always provide clear, concise summaries. When showing diffs, highlight the key changes
rather than dumping raw patches.""",
    tools=[github_mcp_toolset, get_commit_details, correlate_commits_to_tickets],
)

# --- Sub-agent 3: Notifier ---

def send_notification(recipient: str, subject: str, body: str) -> str:
    """Sends a mock email notification to the specified recipient.

    Args:
        recipient: The name or email of the person to notify.
        subject: The email subject line.
        body: The full email body text.

    Returns:
        Confirmation that the notification was sent.
    """
    output = (
        f"\n{'=' * 60}\n"
        f"  MOCK EMAIL SENT\n"
        f"{'=' * 60}\n"
        f"  To:      {recipient}\n"
        f"  Subject: {subject}\n"
        f"{'-' * 60}\n"
        f"{body}\n"
        f"{'=' * 60}\n"
    )
    return output


notifier_agent = Agent(
    model='gemini-2.5-flash',
    name='notifier_agent',
    description=(
        'Drafts and sends notifications: a blocker alert to the responsible '
        'person and a confirmation summary back to the blocked developer.'
    ),
    instruction="""\
You are the Blocker Notifier. You receive two inputs from the orchestrator:
- The **original blocker message** from the blocked developer.
- The **investigation findings** from the investigator agent (JIRA status, GitHub commit activity, ownership map results).

You must produce and send **two messages** using the `send_notification` tool:

---

**Message 1 — Notification to the responsible person:**

Address the person identified as responsible (from the ownership map / JIRA assignee). Include:
- **What is blocked**: The task or module the blocked developer cannot proceed on.
- **Why it's needed**: The dependency and its importance to the blocked developer's work.
- **Current state of their work**: What JIRA and GitHub data show — ticket status, last commit, recency of activity, and any signals of incompleteness.
- **What is specifically needed to unblock**: A clear, actionable ask (e.g. "merge PR #42", "complete the API endpoint", "update the ticket status").

Keep this professional, concise, and actionable. Do not be accusatory — stick to facts.

---

**Message 2 — Summary back to the blocked developer:**

Confirm:
- Who was notified (name and role/team if known).
- What context was shared with them (brief summary of the notification content).
- Any relevant findings they should know about (e.g. the ticket is marked Done but no recent commits, or the assignee changed recently).

Keep this reassuring and informative.

---

Always send both messages via the `send_notification` tool. Use the responsible person's name as recipient for Message 1 and the blocked developer's name for Message 2.""",
    tools=[send_notification],
)

# --- Callbacks ---

import time
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

AUDIT_TABLE = f"{TABLE_COMMITS.rsplit('.', 1)[0]}.agent_audit_log"


def before_agent_callback(callback_context: CallbackContext) -> types.Content | None:
    callback_context.state["_start_time"] = time.time()
    agent_name = callback_context.agent_name
    print(f"[CALLBACK] Agent '{agent_name}' started")

    try:
        bq_client.insert_rows_json(AUDIT_TABLE, [{
            "agent_name": agent_name,
            "event": "start",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }])
    except Exception:
        pass
    return None


def after_agent_callback(callback_context: CallbackContext) -> types.Content | None:
    agent_name = callback_context.agent_name
    start = callback_context.state.get("_start_time", time.time())
    duration_ms = int((time.time() - start) * 1000)
    print(f"[CALLBACK] Agent '{agent_name}' finished in {duration_ms}ms")

    try:
        bq_client.insert_rows_json(AUDIT_TABLE, [{
            "agent_name": agent_name,
            "event": "end",
            "duration_ms": duration_ms,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }])
    except Exception:
        pass
    return None


root_agent = Agent(
    model='gemini-2.5-flash',
    name='root_agent',
    description=(
        'Orchestrator agent that helps developers with project delivery: '
        'resolving blockers, querying commit history and file changes, '
        'checking JIRA ticket status, and coordinating notifications.'
    ),
    instruction="""\
You are the Project Delivery Accelerator. You help developers by:
- Resolving blockers (finding who is blocking and notifying them).
- Answering questions about the project (commits, file changes, PRs, ticket status).
- Syncing data between GitHub, JIRA, and BigQuery.

Determine what the user needs and delegate to the right sub-agent:

**For blocker resolution:**
1. Parse the blocker — extract the developer's task, dependency, and reason.
2. Delegate to `atlassian_agent` to fetch JIRA data.
3. Delegate to `github_sync_agent` to sync commit history.
4. Delegate to `investigator_agent` to cross-reference data and build a factual picture.
5. Delegate to `notifier_agent` to notify the responsible person.
6. Summarize the outcome back to the developer.

**For commit/code queries** (e.g. "show me the last commit", "what files changed", "what did X change"):
- Delegate to `code_analysis_agent` for detailed analysis of commits, diffs, and PRs.
- Delegate to `github_sync_agent` only when syncing commit data to BigQuery is needed.

**For JIRA queries** (e.g. "what's the status of ticket X"):
- Delegate to `atlassian_agent` to fetch the ticket data.

**For investigation queries** (e.g. "who owns this module", "is this ticket stale"):
- Delegate to `investigator_agent` which can query BigQuery and the ownership map.

**For user/team queries** (e.g. "what repos does X have access to", "who is X", "look up user X"):
- Delegate to `investigator_agent` which can look up user profiles and repository access.

If the request is ambiguous, ask clarifying questions before proceeding.""",
    sub_agents=[atlassian_agent, github_sync_agent, code_analysis_agent, investigator_agent, notifier_agent],
    before_agent_callback=before_agent_callback,
    after_agent_callback=after_agent_callback,
)

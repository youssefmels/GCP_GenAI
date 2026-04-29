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

# --- Tool definitions ---

bigquery_toolset = BigQueryToolset()

github_mcp_toolset = McpToolset(
    connection_params=McpStdioConnectionParams(
        server_params=StdioServerParameters(
            command='npx',
            args=['-y', '@modelcontextprotocol/server-github'],
            env={"GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
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
    rows = json.loads(commits_json)
    if not rows:
        return "No commits provided to insert."

    errors = bq_client.insert_rows_json("nse-gcp-ema-tt-575be-sbx-1.task_detail_dataset.github_commit_history", rows)
    if errors:
        return f"Encountered errors inserting rows: {errors}"
    return f"Successfully inserted {len(rows)} commit(s) into github_commit_history."


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
    rows = json.loads(tickets_json)
    if not rows:
        return "No tickets provided to insert."

    errors = bq_client.insert_rows_json("nse-gcp-ema-tt-575be-sbx-1.task_detail_dataset.jira_tickets", rows)
    if errors:
        return f"Encountered errors inserting rows: {errors}"
    return f"Successfully inserted {len(rows)} ticket(s) into jira_tickets."


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
    query = """
        SELECT
            o.module,
            o.owner,
            o.fallback_owner,
            t.full_name,
            t.email,
            t.role,
            t.level
        FROM `nse-gcp-ema-tt-575be-sbx-1.task_detail_dataset.ownership_map` o
        LEFT JOIN `nse-gcp-ema-tt-575be-sbx-1.task_detail_dataset.team_members` t ON o.owner = t.username
        WHERE LOWER(@search_term) LIKE CONCAT('%', LOWER(o.module), '%')
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

1. **Fetch commits from GitHub**
   - Use the GitHub MCP tools to list recent commits for the specified repository.
   - For each commit, gather: the commit SHA, author username, commit message, and timestamp.
   - If a specific file path or module is specified, filter to commits affecting that path.
   - Determine how many files were changed per commit and which top-level modules/directories were affected.

2. **Format the data as JSON**
   - Build a JSON array where each element is an object with these exact keys:
     - "commit_id": the full commit SHA
     - "author": the author's GitHub username
     - "commit_message": the first line of the commit message
     - "files_changed_count": number of files changed (integer)
     - "modules_affected": comma-separated list of top-level directories touched
     - "timestamp": ISO 8601 timestamp (e.g. "2026-04-20T14:30:00Z")

3. **Insert into BigQuery**
   - Call the `insert_github_commits` tool with the JSON array as a string.
   - Report back how many commits were synced and any errors.

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

4. **Return your findings** to the orchestrator as a structured summary:
   - JIRA ticket: ticket_id, title, status, assignee, last updated
   - GitHub activity: last committer, last commit date, number of recent commits, completeness signal
   - Ownership: responsible person (name, email, role) from the ownership map, plus fallback_owner
   - Discrepancies or flags (e.g. assignee ≠ owner, no recent commits, ticket stale)

Be factual and concise. Do not speculate — only report what the data shows.""",
    tools=[bigquery_toolset, github_mcp_toolset, lookup_ownership],
)

# --- Sub-agent 2: Notifier ---

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

root_agent = Agent(
    model='gemini-2.5-flash',
    name='root_agent',
    description=(
        'Orchestrator agent that receives a blocked developer\'s message, '
        'parses the intent, identifies the relevant task or module, and '
        'coordinates two sub-agents in sequence to resolve the blocker and '
        'notify the responsible parties.'
    ),
    instruction="""\
You are the Blocker Resolution Orchestrator. A developer will send you a message describing:
- What they are working on (their current task or module).
- What they depend on (another task, module, team, or person).
- Why they are blocked (the specific impediment).

Your job:
1. **Parse the message** — Extract the developer's name/identity, their current task, the dependency (task, module, or owner), and the reason for the blocker.
2. **Identify the relevant module or task** — Determine which part of the project or which responsible person/team the blocker relates to.
3. **Fetch live JIRA data** — Delegate to `atlassian_agent` with the ticket ID or module name to get the latest JIRA ticket status, assignee, and details directly from JIRA.
4. **Sync GitHub data** — If the blocker involves a specific repository or module, delegate to `github_sync_agent` with the repo and module details so that the `github_commit_history` table in BigQuery has the latest commit data.
5. **Investigate** — Delegate to `investigator_agent` with the parsed blocker details plus any live JIRA data from `atlassian_agent`. It will cross-reference BigQuery data (JIRA tickets, commit history, ownership map) to build a full factual picture.
6. **Notify** — Pass the investigation findings along with the original blocker message to `notifier_agent`. It will draft and send a notification to the responsible person and a confirmation summary back to the blocked developer.
7. **Make the final decision** — Review the notifier's drafted messages before they are sent. Ensure accuracy, appropriate tone, and that the right person is being contacted.

Always confirm the extracted information before delegating. If the developer's message is ambiguous, ask clarifying questions before proceeding.
After all sub-agents complete, summarize the final outcome back to the developer so they know what action was taken and who was notified.""",
    sub_agents=[atlassian_agent, github_sync_agent, investigator_agent, notifier_agent],
)

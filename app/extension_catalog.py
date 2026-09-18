"""Curated extension presets for the LocalAI Desktop catalog.

Presets are metadata only. Installing a preset creates a disabled registry entry.
It does not grant chat/runtime access and it does not store credentials.
"""

PRESET_CATEGORIES = (
    "Productivity",
    "Creativity",
    "Developer Tools",
    "Business & Operations",
)

EXTENSION_PRESETS = (
    {
        "id": "google-calendar",
        "name": "Google Calendar",
        "category": "Productivity",
        "description": "Manage Google Calendar events.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("calendar_read", "calendar_write"),
        "provider_url": "https://calendar.google.com/",
        "docs_url": "https://developers.google.com/calendar/api",
    },
    {
        "id": "notion",
        "name": "Notion",
        "category": "Productivity",
        "description": "Work with Notion pages, databases and workflows.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("docs_read", "docs_write", "database_read", "database_write"),
        "provider_url": "https://www.notion.so/",
        "docs_url": "https://developers.notion.com/",
    },
    {
        "id": "linear",
        "name": "Linear",
        "category": "Productivity",
        "description": "Plan and track product work in Linear.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("issues_read", "issues_write", "projects_read"),
        "provider_url": "https://linear.app/",
        "docs_url": "https://developers.linear.app/",
    },
    {
        "id": "clickup",
        "name": "ClickUp",
        "category": "Productivity",
        "description": "Work with ClickUp tasks and projects.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("tasks_read", "tasks_write", "projects_read"),
        "provider_url": "https://clickup.com/",
        "docs_url": "https://developer.clickup.com/",
    },
    {
        "id": "asana",
        "name": "Asana",
        "category": "Productivity",
        "description": "Turn chats into tasks and project actions.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("tasks_read", "tasks_write", "projects_read"),
        "provider_url": "https://asana.com/",
        "docs_url": "https://developers.asana.com/",
    },
    {
        "id": "dropbox",
        "name": "Dropbox",
        "category": "Productivity",
        "description": "Find, create and manage Dropbox files.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("files_read", "files_write", "files_search"),
        "provider_url": "https://www.dropbox.com/",
        "docs_url": "https://www.dropbox.com/developers",
    },
    {
        "id": "canva",
        "name": "Canva",
        "category": "Creativity",
        "description": "Create and work with Canva designs.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("design_read", "design_create", "design_export"),
        "provider_url": "https://www.canva.com/",
        "docs_url": "https://www.canva.dev/",
    },
    {
        "id": "figma",
        "name": "Figma",
        "category": "Creativity",
        "description": "Read design files and support design-to-code workflows.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("design_read", "comments_read", "assets_read"),
        "provider_url": "https://www.figma.com/",
        "docs_url": "https://www.figma.com/developers/api",
    },
    {
        "id": "gamma",
        "name": "Gamma",
        "category": "Creativity",
        "description": "Create presentations and documents with Gamma.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("presentation_create", "document_create"),
        "provider_url": "https://gamma.app/",
        "docs_url": "",
    },
    {
        "id": "adobe",
        "name": "Adobe",
        "category": "Creativity",
        "description": "Design, combine and edit creative documents.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("document_read", "document_edit", "image_edit"),
        "provider_url": "https://www.adobe.com/",
        "docs_url": "https://developer.adobe.com/",
    },
    {
        "id": "descript",
        "name": "Descript",
        "category": "Creativity",
        "description": "Support media editing workflows.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("media_read", "media_edit", "transcript_read"),
        "provider_url": "https://www.descript.com/",
        "docs_url": "",
    },
    {
        "id": "github",
        "name": "GitHub",
        "category": "Developer Tools",
        "description": "Work with repositories, issues, pull requests and CI.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": (
            "repo_read",
            "repo_write",
            "issues",
            "pull_requests",
            "actions_read",
        ),
        "provider_url": "https://github.com/",
        "docs_url": "https://docs.github.com/en/rest",
    },
    {
        "id": "supabase",
        "name": "Supabase",
        "category": "Developer Tools",
        "description": "Manage and query Supabase projects and databases.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("database_read", "database_write", "project_read"),
        "provider_url": "https://supabase.com/",
        "docs_url": "https://supabase.com/docs",
    },
    {
        "id": "vercel",
        "name": "Vercel",
        "category": "Developer Tools",
        "description": "Inspect and manage web deployments.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("deployments_read", "deployments_write", "projects_read"),
        "provider_url": "https://vercel.com/",
        "docs_url": "https://vercel.com/docs/rest-api",
    },
    {
        "id": "replit",
        "name": "Replit",
        "category": "Developer Tools",
        "description": "Work with Replit development projects.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("project_read", "project_write"),
        "provider_url": "https://replit.com/",
        "docs_url": "https://docs.replit.com/",
    },
    {
        "id": "openai-developers",
        "name": "OpenAI Developers",
        "category": "Developer Tools",
        "description": "Connect OpenAI developer workflows and resources.",
        "type": "http_api",
        "auth_type": "api_key",
        "capabilities": ("api_models", "api_responses"),
        "provider_url": "https://platform.openai.com/",
        "docs_url": "https://platform.openai.com/docs",
    },
    {
        "id": "hubspot",
        "name": "HubSpot",
        "category": "Business & Operations",
        "description": "Work with HubSpot CRM data and workflows.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("crm_read", "crm_write", "contacts_read", "contacts_write"),
        "provider_url": "https://www.hubspot.com/",
        "docs_url": "https://developers.hubspot.com/docs/api/overview",
    },
    {
        "id": "attio",
        "name": "Attio",
        "category": "Business & Operations",
        "description": "Manage CRM records and workflows in Attio.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("crm_read", "crm_write"),
        "provider_url": "https://attio.com/",
        "docs_url": "https://docs.attio.com/rest-api/overview",
    },
    {
        "id": "clay",
        "name": "Clay",
        "category": "Business & Operations",
        "description": "Support GTM data and enrichment workflows.",
        "type": "mcp_connector",
        "auth_type": "api_key",
        "capabilities": ("data_read", "data_enrich"),
        "provider_url": "https://www.clay.com/",
        "docs_url": "",
    },
    {
        "id": "salesforce",
        "name": "Salesforce",
        "category": "Business & Operations",
        "description": "Work with Salesforce CRM records.",
        "type": "mcp_connector",
        "auth_type": "oauth",
        "capabilities": ("crm_read", "crm_write", "contacts_read", "contacts_write"),
        "provider_url": "https://www.salesforce.com/",
        "docs_url": "https://developer.salesforce.com/docs/apis",
    },
)


def all_presets():
    return [dict(item) for item in EXTENSION_PRESETS]


def find_preset(preset_id):
    wanted = str(preset_id or "").strip().casefold()
    for item in EXTENSION_PRESETS:
        if item["id"].casefold() == wanted:
            return dict(item)
    raise KeyError(preset_id)


def search_presets(query="", category=""):
    query = " ".join(str(query or "").casefold().split())
    category = " ".join(str(category or "").strip().split())

    results = []
    for item in EXTENSION_PRESETS:
        if category and category != "All" and item["category"] != category:
            continue

        searchable = " ".join([
            item["name"],
            item["category"],
            item["description"],
            " ".join(item["capabilities"]),
        ]).casefold()

        if query and query not in searchable:
            continue
        results.append(dict(item))
    return results


def preset_to_registry_entry(preset):
    preset = dict(preset or {})
    return {
        "name": preset["name"],
        "type": preset["type"],
        "endpoint": "",
        "enabled": False,
        "auth_type": preset["auth_type"],
        "capabilities": list(preset["capabilities"]),
        "timeout": 10,
        "config": {
            "preset_id": preset["id"],
            "category": preset["category"],
            "description": preset["description"],
            "provider_url": preset.get("provider_url", ""),
            "docs_url": preset.get("docs_url", ""),
        },
    }

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # PostgreSQL
    database_url: str = "postgresql://pokemon:pokemon@localhost:5432/pokemon_monitor"

    # Discord
    discord_enabled: bool = True
    discord_bot_token: str = ""
    discord_webhook_url: str = ""        # #stock-alerts (public)
    discord_admin_webhook: str = ""      # #admin (error alerts)
    discord_discovery_webhook: str = ""  # #new-products
    discord_channel_id: str = ""

    # Redirect service
    redirect_base_url: str = "http://localhost:8080"
    redirect_port: int = 8080

    # Bol.com
    bol_base_url: str = "https://www.bol.com"

    # Polling intervals (seconds)
    poll_interval_product: int = 10
    poll_interval_category: int = 60

    # Category URL paths
    category_paths: list[str] = [
        "/nl/nl/l/pokemon-kaarten/N/8299+16410/",
        "/nl/nl/l/pokemon-kaarten/N/8299+16410/?sortering=4",
    ]

    # Dashboard
    dashboard_auth_enabled: bool = True
    dashboard_user: str = "admin"
    dashboard_pass: str = "changeme"
    dashboard_secret_key: str = "change-me-in-production"
    dashboard_port: int = 3000

    # Railway / generic
    port: int = 8080

    # Mock server
    mock_server_port: int = 8099


settings = Settings()

"""Compatibility wrappers — prefer store.services.fulfillment."""

import logging

from store.services.fulfillment import fulfill_order, parse_order_params  # noqa: F401

logger = logging.getLogger(__name__)


async def create_subscription_for_order(
    content_id,
    days: int,
    template,
    store_name: str = "GG",
    email: str = None,
    hwid: int = None,
    outer_squad_id: str = None,
    user_info=None,
):
    """Legacy wrapper used by older call sites."""
    marketplace = "ggsel" if store_name.upper().startswith("GG") else "digiseller"
    prefix = "gg_id" if marketplace == "ggsel" else "dig_id"
    result = await fulfill_order(
        marketplace=marketplace,
        external_order_id=str(content_id),
        remnawave_username=f"{prefix}{content_id}",
        days=days if days is not None else 30,
        email=email,
        template=template,
        hwid=hwid,
        outer_squad=outer_squad_id,
        chat_id=str(content_id),
    )
    return {"sub": result.get("sub")}


async def get_user_info(username):
    import store.api.remnawave.api as rem

    try:
        user_info = await rem.get_user_from_username(username)
        if user_info:
            expire = user_info.get("expire")
            return {
                "status": "active",
                "expire": expire,
                "subscription_url": user_info.get("subscription_url"),
                "data_limit": None,
                "uuid": user_info.get("uuid"),
            }
        return 404
    except Exception as e:
        logger.error("Error getting user info: %s", e)
        return 404

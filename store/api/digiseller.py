import hashlib
import logging
from typing import Any, Optional

from store.services.fulfillment import fulfill_order, mark_delivered, parse_order_params
from store.settings import secrets
import store.database.requests as rq

logger = logging.getLogger(__name__)


def generate_signature(
    id_value: Any,
    inv_value: Any,
    password: Any,
    model: str = "md5",
) -> Optional[str]:
    id_str = str(id_value) if id_value is not None else ""
    inv_str = str(inv_value) if inv_value is not None else ""
    password_str = str(password) if password is not None else ""
    if model == "md5":
        signature_string = f"{id_str}:{inv_str}:{password_str}"
        return hashlib.md5(signature_string.encode("utf-8")).hexdigest()
    if model == "sha256":
        signature_string = f"{id_str};{inv_str};{password_str}"
        return hashlib.sha256(signature_string.encode("utf-8")).hexdigest()
    return None


def _buyer_email(payment_data: dict) -> str | None:
    for key in ("email", "buyer_email", "mail"):
        if payment_data.get(key):
            return str(payment_data[key])
    options = payment_data.get("options") or []
    for opt in options:
        if isinstance(opt, dict) and opt.get("email"):
            return str(opt["email"])
    return None


async def payment_async_logic(payment_data: dict[str, Any]) -> Any:
    logger.info("Получен вебхук от магазина: %s", payment_data)
    if "id" not in payment_data or "inv" not in payment_data or "options" not in payment_data:
        return 400

    async with rq.get_session() as session:
        item_id = int(payment_data["id"])
        if not await rq.item_id_exists(item_id, session=session):
            return 400

        sign = generate_signature(
            payment_data["id"],
            payment_data["inv"],
            secrets.get("dig_pass"),
        )
        if payment_data.get("sign") != sign:
            logger.warning("Неверная подпись Digiseller inv=%s", payment_data["inv"])
            return 400

        order_params = await parse_order_params(
            item_id=item_id,
            options=payment_data["options"],
            id_key="id",
            data_key="user_data",
            session=session,
        )
        days = order_params["days"] if order_params["days"] is not None else 30
        email = _buyer_email(payment_data)

        # Always go through fulfill_order: verifies Remnawave still has the user;
        # recreates dig_id{inv} if the panel account was deleted (e.g. test inv=0).
        result = await fulfill_order(
            marketplace="digiseller",
            external_order_id=str(payment_data["inv"]),
            remnawave_username=f"dig_id{payment_data['inv']}",
            days=days,
            email=email,
            invoice_id=str(payment_data["inv"]),
            item_id=item_id,
            options=payment_data["options"],
            chat_id=str(payment_data["inv"]),
            template=order_params["template"],
            hwid=order_params["hwid"],
            outer_squad=order_params["outer_squad"],
            digiseller_buyer_id=str(payment_data.get("buyer_id") or payment_data["inv"]),
            session=session,
            allow_extend=False,
        )
        if result.get("sub"):
            await mark_delivered(result["order_id"], session=session)
            await session.commit()
            logger.info(
                "Digiseller inv=%s event=%s url_ok=%s",
                payment_data["inv"],
                result.get("event"),
                bool(result.get("sub")),
            )
            return result["sub"]
        await session.rollback()
        return 400

"""Validate and normalize the transfer context shared by demo stages."""


def parse_uint256(value, *, allow_zero: bool = False) -> int:
    if type(value) is int:
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 78:
        result = int(value)
    else:
        raise ValueError("Expected an integer number of base units")
    if not (0 if allow_zero else 1) <= result < 2**256:
        raise ValueError("Integer is outside the allowed uint256 range")
    return result


def parse_local_transfer(local_transfer):
    asset, raw_limit = local_transfer["asset"], local_transfer["max_amount"]
    raw_claim = local_transfer["claim_amount"]
    if (
        not isinstance(asset, str)
        or not asset
        or isinstance(raw_limit, bool)
        or not isinstance(raw_limit, (str, int))
        or (
            isinstance(raw_limit, str)
            and (not raw_limit.isascii() or not raw_limit.isdecimal() or len(raw_limit) > 78)
        )
    ):
        raise ValueError("A valid local transfer asset and base-unit limit are required")
    limit = int(raw_limit)
    if (
        isinstance(raw_claim, bool)
        or not isinstance(raw_claim, (str, int))
        or (
            isinstance(raw_claim, str)
            and (not raw_claim.isascii() or not raw_claim.isdecimal() or len(raw_claim) > 78)
        )
    ):
        raise ValueError("A valid claim amount in base units is required")
    claim_amount = int(raw_claim)
    if not 0 < limit < claim_amount < 2**256:
        raise ValueError("Claim amount must exceed the local transfer limit")
    return asset, limit, claim_amount

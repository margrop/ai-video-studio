"""Build deterministic social drafts from a validated StoryPlan."""

from __future__ import annotations

from pathlib import Path

from packages.contracts.models import SocialDraft, SocialDraftBundle, SocialPlatform, StoryPlan

DEFAULT_PLATFORMS: tuple[SocialPlatform, ...] = (
    "blog",
    "wechat",
    "zhihu",
    "bilibili",
    "xiaohongshu",
    "douyin",
    "podcast",
)


def _hashtags(plan: StoryPlan) -> list[str]:
    words = [word.strip("，。！？,. ") for word in plan.title.split() if word.strip()]
    return [f"#{word}" for word in words[:4]] or ["#AI", "#内容创作"]


def build_social_drafts(
    plan: StoryPlan,
    platforms: tuple[SocialPlatform, ...] = DEFAULT_PLATFORMS,
) -> SocialDraftBundle:
    drafts: list[SocialDraft] = []
    tags = _hashtags(plan)
    for platform in platforms:
        if platform == "blog":
            body = f"{plan.summary}\n\n{plan.narration}"
        elif platform in {"wechat", "zhihu"}:
            body = f"{plan.summary}\n\n核心内容：{plan.narration}\n\n欢迎收藏和转发。"
        elif platform == "podcast":
            body = f"节目简介：{plan.summary}\n\n本期口播：{plan.narration}"
        else:
            body = f"{plan.summary}\n\n一分钟看懂：{plan.title}。"
        drafts.append(
            SocialDraft(
                platform=platform,
                title=plan.title,
                body=body[:20_000],
                hashtags=tags,
            )
        )
    return SocialDraftBundle(plan_id=plan.plan_id, drafts=drafts)


def write_social_drafts(
    plan: StoryPlan,
    output_path: Path,
    platforms: tuple[SocialPlatform, ...] = DEFAULT_PLATFORMS,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = build_social_drafts(plan, platforms)
    output_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    return output_path

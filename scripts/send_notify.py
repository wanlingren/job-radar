#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
江浙沪皖国资招聘雷达 - 企业微信批量推送

功能：
1. 获取所有未推送招聘；
2. 江浙沪皖优先；
3. 不限制8条；
4. 自动将大量岗位拆成多条企业微信消息；
5. 每一批成功后立即记录为已推送；
6. 发送失败的岗位不做标记，下次继续发送；
7. 防止单条企业微信消息过长；
8. 检查企业微信业务层 errcode。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

import notify_preview


# ============================================================
# 企业微信消息控制
# ============================================================

# 不把消息撑到极限，
# 给Markdown、中文UTF-8等预留安全空间。
MAX_MARKDOWN_BYTES = 3300

# 每两条企业微信消息之间等待4秒，
# 避免发送过快。
SEND_INTERVAL_SECONDS = 4


# ============================================================
# Webhook
# ============================================================

def webhook_from_env() -> str:

    return (
        os.getenv(
            "WECHAT_WEBHOOK_URL",
            "",
        ).strip()
        or
        os.getenv(
            "WECOM_WEBHOOK_URL",
            "",
        ).strip()
    )


# ============================================================
# HTTP请求
# ============================================================

def post_json(
    url: str,
    payload: dict,
    timeout: int = 20,
) -> tuple[int, str]:

    data = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": (
                "application/json"
            ),
        },
        method="POST",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:

            return (
                response.status,
                response.read().decode(
                    "utf-8",
                    errors="ignore",
                ),
            )

    except urllib.error.HTTPError as exc:

        return (
            exc.code,
            exc.read().decode(
                "utf-8",
                errors="ignore",
            ),
        )

    except urllib.error.URLError as exc:

        return (
            0,
            str(exc),
        )

    except Exception as exc:

        return (
            0,
            str(exc),
        )


# ============================================================
# 判断企业微信是否真正发送成功
# ============================================================

def wecom_success(
    status: int,
    body: str,
) -> bool:

    if not (
        200
        <= status
        < 300
    ):
        return False

    try:

        result = json.loads(
            body
        )

    except json.JSONDecodeError:
        return False

    return (
        result.get(
            "errcode",
            -1,
        )
        == 0
    )


# ============================================================
# 企业微信payload
# ============================================================

def payload(
    text: str,
) -> dict:

    return {
        "msgtype": "markdown",
        "markdown": {
            "content": text,
        },
    }


# ============================================================
# 单个招聘Markdown
# ============================================================

def job_block(
    job: dict,
) -> str:

    return (
        notify_preview.line(job)
        + "\n\n"
    )


# ============================================================
# 根据地区分组
# ============================================================

def group_by_region(
    jobs: list[dict],
) -> dict[str, list[dict]]:

    result = {
        "浙江": [],
        "江苏": [],
        "上海": [],
        "安徽": [],
        "其他地区": [],
    }

    for job in jobs:

        region = (
            notify_preview.region_name(
                job
            )
        )

        result.setdefault(
            region,
            [],
        ).append(job)

    return result


# ============================================================
# 自动拆分企业微信消息
# ============================================================

def split_region_batches(
    region: str,
    jobs: list[dict],
    workbench_url: str,
) -> list[
    tuple[
        str,
        list[dict],
    ]
]:

    if not jobs:
        return []

    raw_batches: list[
        tuple[
            str,
            list[dict],
        ]
    ] = []

    current_text = ""
    current_jobs: list[dict] = []

    # 给标题、链接、批次信息预留空间
    safe_body_limit = (
        MAX_MARKDOWN_BYTES
        - 600
    )

    for job in jobs:

        block = job_block(job)

        prospective = (
            current_text
            + block
        )

        prospective_size = len(
            prospective.encode(
                "utf-8"
            )
        )

        if (
            current_jobs
            and prospective_size
            > safe_body_limit
        ):

            raw_batches.append(
                (
                    current_text,
                    current_jobs,
                )
            )

            current_text = ""
            current_jobs = []

        # 极端情况：
        # 单个岗位描述自身过长
        # notify_preview.line本身很短，
        # 正常不会触发。
        current_text += block

        current_jobs.append(
            job
        )

    if current_jobs:

        raw_batches.append(
            (
                current_text,
                current_jobs,
            )
        )

    final_batches: list[
        tuple[
            str,
            list[dict],
        ]
    ] = []

    total_parts = len(
        raw_batches
    )

    for index, (
        body,
        rows,
    ) in enumerate(
        raw_batches,
        start=1,
    ):

        header = (
            "# 🎯 江浙沪皖国资招聘雷达\n"
            f"> 📍 **{region}**"
            f"｜第 {index}/{total_parts} 批"
            f"｜本批 {len(rows)} 条\n\n"
        )

        if workbench_url:

            header += (
                "[📋 查看完整招聘信息台]"
                f"({workbench_url})\n\n"
            )

        text = (
            header
            + body
            + (
                "> ✅ 已成功推送岗位"
                "自动去重"
            )
        )

        # 再检查一次最终字节大小
        size = len(
            text.encode(
                "utf-8"
            )
        )

        if size > MAX_MARKDOWN_BYTES:

            print(
                "::warning::"
                f"{region} 第{index}批"
                f"消息较长：{size} bytes"
            )

        final_batches.append(
            (
                text,
                rows,
            )
        )

    return final_batches


# ============================================================
# 建立全部发送批次
# ============================================================

def build_batches(
    selected: list[dict],
    workbench_url: str,
) -> list[
    tuple[
        str,
        list[dict],
    ]
]:

    grouped = group_by_region(
        selected
    )

    batches: list[
        tuple[
            str,
            list[dict],
        ]
    ] = []

    # 江浙沪皖永远优先发送
    for region in (
        "浙江",
        "江苏",
        "上海",
        "安徽",
        "其他地区",
    ):

        region_jobs = grouped.get(
            region,
            [],
        )

        batches.extend(
            split_region_batches(
                region,
                region_jobs,
                workbench_url,
            )
        )

    return batches


# ============================================================
# 主程序
# ============================================================

def main() -> None:

    parser = argparse.ArgumentParser(
        description=(
            "江浙沪皖国资招聘雷达"
            "企业微信批量推送"
        )
    )

    parser.add_argument(
        "--out",
        default=notify_preview.OUT,
    )

    parser.add_argument(
        "--state",
        default=notify_preview.STATE,
    )

    # 以下参数继续保留，
    # 避免原GitHub Actions调用时报错。
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--min-focus",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--min-match",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--since",
        default="",
    )

    parser.add_argument(
        "--include-existing-due",
        action="store_true",
    )

    parser.add_argument(
        "--webhook",
        default="",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--no-mark",
        action="store_true",
    )

    parser.add_argument(
        "--workbench-url",
        default=os.getenv(
            "WORKBENCH_URL",
            "",
        ).strip(),
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # 获取全部未推送岗位
    # --------------------------------------------------------

    markdown_preview, selected = (
        notify_preview.build(
            limit=0,
            min_focus=0,
            min_match=0,
            mode="new",
            since=args.since,
            include_existing_due=(
                args.include_existing_due
            ),
            state_path=args.state,
            workbench_url=(
                args.workbench_url
            ),
        )
    )

    # 保存完整预览
    os.makedirs(
        os.path.dirname(args.out),
        exist_ok=True,
    )

    with open(
        args.out,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            markdown_preview
        )

    # --------------------------------------------------------
    # 没有新招聘
    # --------------------------------------------------------

    if not selected:

        print(
            "✅ 当前没有未推送的"
            "新增招聘信息。"
        )

        return

    print("=" * 60)

    print(
        "🎯 江浙沪皖国资招聘雷达"
    )

    print(
        f"📦 待推送岗位总数："
        f"{len(selected)}"
    )

    # 地区统计
    grouped = group_by_region(
        selected
    )

    for region in (
        "浙江",
        "江苏",
        "上海",
        "安徽",
        "其他地区",
    ):

        print(
            f"  - {region}: "
            f"{len(grouped.get(region, []))} 条"
        )

    # --------------------------------------------------------
    # Webhook
    # --------------------------------------------------------

    webhook = (
        args.webhook.strip()
        or webhook_from_env()
    )

    # --------------------------------------------------------
    # 自动拆分批次
    # --------------------------------------------------------

    batches = build_batches(
        selected,
        args.workbench_url,
    )

    print(
        f"📨 自动拆分为 "
        f"{len(batches)} 条"
        "企业微信消息"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # dry-run
    # --------------------------------------------------------

    if args.dry_run:

        print(
            "⚠️ 当前为 dry-run，"
            "不会真正发送。"
        )

        return

    if not webhook:

        print(
            "❌ 未找到企业微信Webhook。"
        )

        print(
            "请检查GitHub Secret："
            "WECHAT_WEBHOOK_URL"
        )

        sys.exit(1)

    # --------------------------------------------------------
    # 开始逐批发送
    # --------------------------------------------------------

    successful_jobs = 0

    failed_jobs = 0

    successful_batches = 0

    failed_batches = 0

    for index, (
        text,
        rows,
    ) in enumerate(
        batches,
        start=1,
    ):

        message_size = len(
            text.encode(
                "utf-8"
            )
        )

        region = (
            notify_preview.region_name(
                rows[0]
            )
            if rows
            else "未知"
        )

        print(
            f"📨 发送第 "
            f"{index}/{len(batches)} 批"
        )

        print(
            f"   地区：{region}"
        )

        print(
            f"   岗位：{len(rows)} 条"
        )

        print(
            f"   消息大小："
            f"{message_size} bytes"
        )

        status, body = post_json(
            webhook,
            payload(text),
        )

        if wecom_success(
            status,
            body,
        ):

            successful_batches += 1

            successful_jobs += len(
                rows
            )

            print(
                f"✅ 第 {index} 批"
                "发送成功"
            )

            # 只有真正发送成功后
            # 才写入去重状态
            if not args.no_mark:

                added = (
                    notify_preview.mark_pushed(
                        args.state,
                        rows,
                    )
                )

                print(
                    f"✅ 已记录 "
                    f"{added} 条为已推送"
                )

        else:

            failed_batches += 1

            failed_jobs += len(
                rows
            )

            print(
                "::warning::"
                f"第 {index} 批发送失败"
            )

            print(
                f"HTTP状态：{status}"
            )

            print(
                f"企业微信返回：{body}"
            )

            print(
                "⚠️ 本批岗位不会写入"
                "已推送状态，"
                "下次会自动重试。"
            )

        # 避免机器人发送过快
        if index < len(batches):

            time.sleep(
                SEND_INTERVAL_SECONDS
            )

    # --------------------------------------------------------
    # 最终统计
    # --------------------------------------------------------

    print("=" * 60)

    print(
        "📊 推送结果"
    )

    print(
        f"✅ 成功批次："
        f"{successful_batches}"
    )

    print(
        f"✅ 成功岗位："
        f"{successful_jobs}"
    )

    print(
        f"⚠️ 失败批次："
        f"{failed_batches}"
    )

    print(
        f"⚠️ 失败岗位："
        f"{failed_jobs}"
    )

    print("=" * 60)

    # 全部失败才让Action报错
    if (
        batches
        and successful_batches == 0
    ):

        print(
            "❌ 所有企业微信消息"
            "均发送失败。",
            file=sys.stderr,
        )

        sys.exit(1)

    # 部分失败不退出，
    # 成功的state让后面的Commit data保存；
    # 失败的下次自动重试。
    if failed_batches > 0:

        print(
            "::warning::"
            "部分消息发送失败。"
            "失败岗位将在下一次"
            "自动运行时重新发送。"
        )

    else:

        print(
            "🎉 所有招聘信息"
            "均已成功推送。"
        )


if __name__ == "__main__":
    main()

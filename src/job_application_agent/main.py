import asyncio
import sys

from job_application_agent.config import Settings
from job_application_agent.user_info.parser import load_user_info
from job_application_agent.context import CompanyState, RECRUITMENT_TYPES
from job_application_agent.agents.orchestrator import run_job_application


def main():
    print("=" * 60)
    print("🎓 简历自动投递Agent")
    print("=" * 60)

    settings = Settings()
    errors = settings.validate()
    if errors:
        print("\n❌ 配置错误:")
        for error in errors:
            print(f"  - {error}")
        print("\n请在 .env 文件中配置以上项目后重试。")
        sys.exit(1)

    print("\n✅ 配置验证通过")

    user_info = load_user_info(
        settings.personal_info_file_path,
        settings.resume_file_path,
    )

    missing = user_info.get_missing_fields()
    if missing:
        print(f"\n⚠️ 以下信息缺失: {', '.join(missing)}")
        print("建议补充这些信息以获得更好的填写效果。")

    print(f"\n📋 用户信息摘要:")
    print(user_info.to_summary())

    recruitment_type = _ask_recruitment_type()

    companies = _collect_company_input(recruitment_type)

    if not companies:
        print("\n未输入任何公司，退出。")
        sys.exit(0)

    parallel = _ask_parallel_mode()

    print(f"\n🚀 开始处理 {len(companies)} 家公司的投递（{'并行' if parallel else '顺序'}模式，{recruitment_type}）...")
    results = asyncio.run(run_job_application(user_info, companies, parallel=parallel))

    print("\n" + "=" * 60)
    print("📊 投递结果汇总:")
    print("=" * 60)
    for company_name, result in results.items():
        status_emoji = "✅" if result.get("submitted") else "⏸️"
        print(f"\n{status_emoji} {company_name}:")
        print(f"  状态: {result.get('status', 'unknown')}")
        print(f"  表单填写: {'完成' if result.get('form_filled') else '未完成'}")
        print(f"  投递: {'已投递' if result.get('submitted') else '未投递'}")
        if result.get("error_message") or result.get("error"):
            print(f"  错误: {result.get('error_message') or result.get('error')}")


def _ask_recruitment_type() -> str:
    print("\n📌 请选择投递类型:")
    for i, rt in enumerate(RECRUITMENT_TYPES, 1):
        print(f"  {i}. {rt}")
    while True:
        choice = input("请输入编号（1-4）: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(RECRUITMENT_TYPES):
            selected = RECRUITMENT_TYPES[int(choice) - 1]
            print(f"  ✅ 已选择: {selected}")
            return selected
        print("  ❌ 无效输入，请重新选择")


def _collect_company_input(recruitment_type: str) -> list[CompanyState]:
    companies = []
    print(f"\n📝 请输入要投递的公司信息（投递类型: {recruitment_type}，输入空行结束）:")
    print("-" * 40)

    while True:
        company_name = input("\n公司名称（直接回车结束输入）: ").strip()
        if not company_name:
            break

        referral_code = input("内推码（没有则直接回车）: ").strip()
        job_keywords = input("岗位关键词（如：AI算法、agent开发）: ").strip()
        cities_str = input("期望工作城市（多个城市用逗号分隔）: ").strip()
        preferred_cities = [c.strip() for c in cities_str.split(",") if c.strip()] if cities_str else []

        company = CompanyState(
            company_name=company_name,
            recruitment_type=recruitment_type,
            referral_code=referral_code,
            job_keywords=job_keywords,
            preferred_cities=preferred_cities,
        )
        companies.append(company)
        print(f"  ✅ 已添加: {company_name}（{recruitment_type}）")

    return companies


def _ask_parallel_mode() -> bool:
    choice = input("\n是否启用并行模式（同时处理多家公司）？(y/n，默认n): ").strip().lower()
    return choice in ("y", "yes", "是")


if __name__ == "__main__":
    main()

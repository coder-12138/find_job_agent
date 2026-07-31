"""Deterministic local recruiting site for managed-browser E2E tests."""

from html import escape

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse


app = FastAPI(title="Simulated Recruiting Site", version="1")


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{escape(title)}</title></head>
<body data-simulated-recruiting-site="true">
  <main><h1>{escape(title)}</h1>{body}</main>
</body>
</html>"""
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "site": "simulated-recruiting"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(return_to: str = "/jobs/demo/apply") -> HTMLResponse:
    safe_return = return_to if return_to.startswith("/") else "/jobs/demo/apply"
    return page(
        "模拟招聘登录",
        f"""
        <form method="post" action="/login">
          <input type="hidden" name="return_to" value="{escape(safe_return)}">
          <label>邮箱 <input name="email" type="email" required></label>
          <button type="submit">登录</button>
        </form>
        """,
    )


@app.post("/login")
async def login(email: str = Form(...), return_to: str = Form("/jobs/demo/apply")):
    destination = return_to if return_to.startswith("/") else "/jobs/demo/apply"
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        "simulated_recruiting_session", "authenticated", httponly=True, samesite="strict"
    )
    response.set_cookie("simulated_candidate", email, samesite="strict")
    return response


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job(job_id: str) -> HTMLResponse:
    return page(
        "模拟招聘职位",
        f"""
        <article data-job-id="{escape(job_id)}">
          <p data-job-description>这是只用于端到端测试的本地职位，不联系真实平台。</p>
          <a href="/jobs/{escape(job_id)}/apply">立即申请</a>
        </article>
        """,
    )


@app.get("/jobs/{job_id}/apply", response_class=HTMLResponse)
async def application_form(request: Request, job_id: str):
    if request.cookies.get("simulated_recruiting_session") != "authenticated":
        return RedirectResponse(f"/login?return_to=/jobs/{job_id}/apply", status_code=303)
    candidate = request.cookies.get("simulated_candidate", "")
    return page(
        "模拟职位申请",
        f"""
        <form method="post" action="/jobs/{escape(job_id)}/submit" enctype="multipart/form-data">
          <label>姓名 <input name="full_name" data-field-key="full_name" required></label>
          <label>邮箱 <input name="email" data-field-key="email" type="email" value="{escape(candidate)}" required></label>
          <label>手机 <input name="phone" data-field-key="phone" required></label>
          <label>原始简历 <input name="resume" type="file" accept="application/pdf"></label>
          <label>测试结果
            <select name="outcome" data-field-key="test_outcome">
              <option value="success">显示成功回执</option>
              <option value="unknown">结果未知</option>
              <option value="rejected">提交失败</option>
            </select>
          </label>
          <button type="submit" data-final-submit="true">最终提交</button>
        </form>
        """,
    )


@app.post("/jobs/{job_id}/submit", response_class=HTMLResponse)
async def submit_application(
    request: Request,
    job_id: str,
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    outcome: str = Form("success"),
):
    del full_name, email, phone
    if request.cookies.get("simulated_recruiting_session") != "authenticated":
        return RedirectResponse(f"/login?return_to=/jobs/{job_id}/apply", status_code=303)
    if outcome == "unknown":
        response = page(
            "提交结果未知",
            '<p data-submission-state="unknown">服务未返回可验证回执。</p>',
        )
        response.status_code = 202
        return response
    if outcome == "rejected":
        response = page(
            "提交失败",
            '<p data-submission-state="rejected">模拟平台拒绝了本次提交。</p>',
        )
        response.status_code = 422
        return response
    return page(
        "申请提交成功",
        f"""
        <p data-submission-state="submitted">职位申请 {escape(job_id)} 已成功提交。</p>
        <code data-submission-receipt="true">SIM-{escape(job_id.upper())}-0001</code>
        """,
    )

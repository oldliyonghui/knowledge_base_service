import json
import time
from datetime import datetime

import requests
import streamlit as st

API = "http://127.0.0.1:8000/api/v1"


# ==================== 工具函数 ====================
def api(method, path, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return requests.request(method, API + path, headers=headers,
                                timeout=120, **kwargs)
    except requests.RequestException as e:
        st.error(f"网络错误: {e}")
        return None


def show_error(r, prefix="请求失败"):
    if r is None:
        return
    try:
        detail = r.json().get("detail", r.text)
    except Exception:
        detail = r.text
    st.error(f"{prefix}: HTTP {r.status_code} - {detail}")


def fmt_time(s):
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return s[:16]


# ==================== 页面 ====================
st.set_page_config(page_title="RAG 调试台", layout="wide")
st.title("RAG 知识库调试台")

defaults = {
    "token": "", "user": None,
    "current_kb": None,
    "current_session": None,
    "messages": [],
    "show_citations": True,
    "kb_list": [],
    "session_list": [],
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ==================== 侧边栏：登录 + 知识库 ====================
with st.sidebar:
    st.header("🔐 登录")
    if not st.session_state.token:
        username = st.text_input("用户名", "admin")
        password = st.text_input("密码", "admin123456", type="password")
        if st.button("登录", use_container_width=True):
            r = api("POST", "/auth/login",
                    json={"username": username, "password": password})
            if r and r.ok:
                d = r.json()
                st.session_state.token = d["access_token"]
                st.session_state.user = d["user"]
                st.rerun()
            else:
                show_error(r, "登录失败")
    else:
        u = st.session_state.user or {}
        st.success(f"👤 {u.get('username', '?')}")
        if st.button("退出登录", use_container_width=True):
            for k in defaults:
                st.session_state[k] = defaults[k]
            st.rerun()

token = st.session_state.token
if not token:
    st.info("👈 请在左侧登录")
    st.stop()

with st.sidebar:
    st.divider()
    st.header("📚 当前知识库")
    if st.button("🔄 刷新", use_container_width=True):
        r = api("GET", "/kbs", token=token)
        if r and r.ok:
            st.session_state.kb_list = r.json().get("items", [])

    if not st.session_state.kb_list:
        r = api("GET", "/kbs", token=token)
        if r and r.ok:
            st.session_state.kb_list = r.json().get("items", [])

    kbs = st.session_state.kb_list
    if kbs:
        options = {f"{k['name']} ({k['doc_count']})": k for k in kbs}
        labels = list(options.keys())
        default_idx = 0
        if st.session_state.current_kb:
            for i, lab in enumerate(labels):
                if options[lab]["id"] == st.session_state.current_kb["id"]:
                    default_idx = i
                    break
        sel = st.selectbox("选择知识库", labels, index=default_idx)
        st.session_state.current_kb = options[sel]
    else:
        st.info("还没有知识库，去「知识库」Tab 创建")


# ==================== 主区域：三个 Tab ====================
tab_kb, tab_doc, tab_chat = st.tabs(["📚 知识库", "📄 文档", "💬 聊天"])


# =========================================================
# Tab 1: 知识库
# =========================================================
with tab_kb:
    st.subheader("创建知识库")
    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        new_name = st.text_input("名称", key="kb_new_name",
                                 placeholder="研发知识库")
    with col2:
        vis = st.selectbox("可见性", ["private", "tenant", "public"],
                           key="kb_vis")
    with col3:
        st.write("")
        st.write("")
        if st.button("创建", key="btn_create_kb",
                     use_container_width=True):
            if not new_name:
                st.warning("请输入名称")
            else:
                r = api("POST", "/kbs", token=token,
                        json={"name": new_name, "visibility": vis})
                if r and r.ok:
                    st.success(f"创建成功: {r.json()['id']}")
                    # 刷新 KB 列表
                    r2 = api("GET", "/kbs", token=token)
                    if r2 and r2.ok:
                        st.session_state.kb_list = r2.json().get("items", [])
                    st.rerun()
                else:
                    show_error(r, "创建失败")

    st.divider()
    st.subheader("知识库列表")

    if st.button("🔄 刷新列表", key="btn_refresh_kb"):
        r = api("GET", "/kbs", token=token)
        if r and r.ok:
            st.session_state.kb_list = r.json().get("items", [])
        st.rerun()

    for kb in st.session_state.kb_list:
        with st.container(border=True):
            cols = st.columns([4, 1, 1, 1])
            with cols[0]:
                st.markdown(
                    f"**{kb['name']}**  \n"
                    f"`{kb['id']}`  \n"
                    f"文档 {kb['doc_count']} · chunk {kb['chunk_count']} · "
                    f"可见性 **{kb['visibility']}**"
                )
            with cols[1]:
                if st.button("查看权限", key=f"perm_{kb['id']}"):
                    r = api("GET", f"/kbs/{kb['id']}/my-permission",
                            token=token)
                    if r and r.ok:
                        st.json(r.json())
                    else:
                        show_error(r)
            with cols[2]:
                if st.button("设为当前", key=f"set_{kb['id']}"):
                    st.session_state.current_kb = kb
                    st.rerun()
            with cols[3]:
                if st.button("删除", key=f"del_kb_{kb['id']}",
                             type="secondary"):
                    r = api("DELETE", f"/kbs/{kb['id']}", token=token)
                    if r and (r.ok or r.status_code == 204):
                        st.success("已删除")
                        st.session_state.kb_list = [
                            k for k in st.session_state.kb_list
                            if k["id"] != kb["id"]
                        ]
                        if (st.session_state.current_kb
                                and st.session_state.current_kb["id"] == kb["id"]):
                            st.session_state.current_kb = None
                        st.rerun()
                    elif r and r.status_code == 405:
                        st.warning("后端未实现 DELETE /kbs/{id}")
                    else:
                        show_error(r, "删除失败")


# =========================================================
# Tab 2: 文档
# =========================================================
with tab_doc:
    kb = st.session_state.current_kb
    if not kb:
        st.info("请先在左侧选择一个知识库")
    else:
        st.subheader(f"上传到：{kb['name']}")

        uploaded = st.file_uploader("选择 PDF", type=["pdf"],
                                    key="file_uploader")
        if uploaded is not None and st.button("开始上传", key="btn_upload"):
            files = {"file": (uploaded.name, uploaded.getvalue(),
                              "application/pdf")}
            r = api("POST", f"/kbs/{kb['id']}/documents/upload",
                    token=token, files=files)
            if not r or not r.ok:
                show_error(r, "上传失败")
            else:
                d = r.json()
                st.session_state["last_doc_id"] = d["doc_id"]
                st.success(f"上传成功 doc_id={d['doc_id']}")

        st.divider()
        st.subheader("文档列表")
        if st.button("🔄 刷新列表", key="btn_refresh_doc"):
            st.rerun()

        r = api("GET", f"/documents?kb_id={kb['id']}", token=token)
        if r and r.ok:
            docs = r.json().get("items", [])
            if not docs:
                st.info("暂无文档")
            for d in docs:
                with st.container(border=True):
                    cols = st.columns([4, 1, 1, 1])
                    with cols[0]:
                        st.markdown(
                            f"**{d['file_name']}**  \n"
                            f"`{d['id']}`  \n"
                            f"大小 {d['file_size']/1024:.1f} KB · "
                            f"状态 **{d['status']}**"
                        )
                    with cols[1]:
                        if st.button("查状态", key=f"st_{d['id']}"):
                            sr = api("GET", f"/documents/{d['id']}/status",
                                     token=token)
                            if sr and sr.ok:
                                st.json(sr.json())
                            else:
                                show_error(sr)
                    with cols[2]:
                        if st.button("预览", key=f"prev_{d['id']}"):
                            st.session_state["preview_doc_id"] = d["id"]
                    with cols[3]:
                        if st.button("删除", key=f"del_doc_{d['id']}",
                                     type="secondary"):
                            rr = api("DELETE", f"/documents/{d['id']}",
                                     token=token)
                            if rr and (rr.ok or rr.status_code == 204):
                                st.success("已提交删除")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                show_error(rr, "删除失败")

        # 自动轮询最近上传的文档
        last_doc_id = st.session_state.get("last_doc_id")
        if last_doc_id:
            st.divider()
            st.subheader("最近上传的文档状态")
            placeholder = st.empty()
            for _ in range(90):
                sr = api("GET", f"/documents/{last_doc_id}/status",
                         token=token)
                if not sr or not sr.ok:
                    break
                s = sr.json()
                placeholder.markdown(
                    f"**{s['status']}** — "
                    f"进度 {int((s.get('progress') or 0) * 100)}%"
                    + (f"\n\n❌ {s.get('error_msg')}" if s.get("error_msg") else "")
                )
                if s["status"] in ("indexed", "failed"):
                    break
                time.sleep(2)


# =========================================================
# Tab 3: 聊天
# =========================================================
def load_sessions():
    r = api("GET", "/chat/sessions", token=token,
            params={"page": 1, "page_size": 50})
    if r and r.ok:
        return r.json().get("items", [])
    return []


def load_messages(session_id):
    r = api("GET", f"/chat/sessions/{session_id}/messages", token=token,
            params={"page": 1, "page_size": 200})
    if r and r.ok:
        return r.json().get("items", [])
    return []


def create_session(kb_id):
    r = api("POST", "/chat/sessions", token=token,
            json={"title": "新会话", "kb_ids": [kb_id]})
    if r and r.ok:
        return r.json()
    show_error(r, "建会话失败")
    return None


def delete_session(sid):
    r = api("DELETE", f"/chat/sessions/{sid}", token=token)
    return r and (r.ok or r.status_code == 204)


def render_citations(citations):
    """引用列表：文档名、页码、分数、原文。"""
    if not citations:
        return
    with st.expander(f"📎 引用 {len(citations)} 条", expanded=False):
        for i, c in enumerate(citations, 1):
            fn = c.get("file_name") or "未知"
            ps, pe = c.get("page_start"), c.get("page_end")
            score = c.get("score")
            rr = c.get("rerank_score")

            page_str = ""
            if ps and pe:
                page_str = f"p.{ps}" if ps == pe else f"p.{ps}-{pe}"
            elif ps:
                page_str = f"p.{ps}"

            score_str = ""
            if rr is not None:
                score_str = f"rerank={rr:.3f}"
            elif score is not None:
                score_str = f"cos={score:.3f}"

            st.markdown(f"**[{i}]** `{fn}` {page_str} · {score_str}")
            content = c.get("content", "")
            if content:
                st.caption(content[:500] + ("..." if len(content) > 500 else ""))


def render_message(msg):
    role = msg.get("role", "assistant")
    content = msg.get("content", "")
    citations = msg.get("citations") or []
    with st.chat_message("user" if role == "user" else "assistant"):
        st.markdown(content)
        if role == "assistant" and st.session_state.show_citations and citations:
            render_citations(citations)


with tab_chat:
    kb = st.session_state.current_kb
    if not kb:
        st.info("请先在左侧选择知识库")
    else:
        # 两列：左会话列表，右聊天
        col_sessions, col_chat = st.columns([1, 3])

        # ---- 左列：会话管理 ----
        with col_sessions:
            st.markdown("##### 💬 会话")

            if st.button("➕ 新建会话", use_container_width=True):
                new_s = create_session(kb["id"])
                if new_s:
                    st.session_state.current_session = new_s
                    st.session_state.messages = []
                    st.session_state.session_list = load_sessions()
                    st.rerun()

            if not st.session_state.session_list:
                st.session_state.session_list = load_sessions()

            for s in st.session_state.session_list:
                is_current = (
                    st.session_state.current_session
                    and st.session_state.current_session["id"] == s["id"]
                )
                c1, c2 = st.columns([5, 1])
                with c1:
                    label = f"{'▶ ' if is_current else ''}{s['title'][:16]}"
                    if st.button(label, key=f"sel_{s['id']}",
                                 use_container_width=True):
                        st.session_state.current_session = s
                        st.session_state.messages = load_messages(s["id"])
                        st.rerun()
                with c2:
                    if st.button("🗑", key=f"del_{s['id']}"):
                        if delete_session(s["id"]):
                            if (st.session_state.current_session
                                    and st.session_state.current_session["id"] == s["id"]):
                                st.session_state.current_session = None
                                st.session_state.messages = []
                            st.session_state.session_list = load_sessions()
                            st.rerun()

        # ---- 右列：聊天区 ----
        with col_chat:
            session = st.session_state.current_session
            if not session:
                st.info("👈 左侧新建或选择一个会话")
            else:
                head1, head2 = st.columns([3, 1])
                with head1:
                    st.markdown(f"##### {session['title']}")
                    st.caption(f"会话 ID: `{session['id']}`")
                with head2:
                    st.session_state.show_citations = st.toggle(
                        "显示引用详情",
                        value=st.session_state.show_citations,
                    )

                st.divider()

                # 历史消息
                for m in st.session_state.messages:
                    render_message(m)

                # 输入
                q = st.chat_input("输入问题...")
                if q:
                    um = {"role": "user", "content": q}
                    st.session_state.messages.append(um)
                    render_message(um)

                    with st.chat_message("assistant"):
                        with st.spinner("检索中..."):
                            r = api(
                                "POST",
                                f"/chat/sessions/{session['id']}/messages",
                                token=token,
                                json={"question": q, "kb_ids": [kb["id"]]},
                            )
                        if not r or not r.ok:
                            st.error("提问失败")
                            show_error(r)
                        else:
                            d = r.json()
                            ans = d["assistant_message"]["content"]
                            cits = d.get("citations", [])
                            st.markdown(ans)
                            if st.session_state.show_citations and cits:
                                render_citations(cits)
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": ans,
                                "citations": cits,
                            })
                            st.session_state.session_list = load_sessions()
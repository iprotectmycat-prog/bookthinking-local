"use client";

import { type FormEvent, useEffect, useState } from "react";
import Link from "next/link";

import { apiJson } from "../lib/api";
import type { AdminBook } from "../lib/types";

type User = { id: number; email: string; status: string; role: string; book_import_count: number; book_import_limit: number | null };
type Invite = { id: number; status: "active" | "used" | "revoked"; label: string | null; used_by_user_id: number | null };

export function AdminExperience() {
  const [users, setUsers] = useState<User[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [books, setBooks] = useState<AdminBook[]>([]);
  const [label, setLabel] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [quotaDrafts, setQuotaDrafts] = useState<Record<number, string>>({});
  const [rightsConfirmed, setRightsConfirmed] = useState<Record<string, boolean>>({});

  const refresh = () => Promise.all([apiJson<User[]>("/admin/users"), apiJson<Invite[]>("/admin/invites"), apiJson<AdminBook[]>("/admin/books")])
    .then(([userItems, inviteItems, bookItems]) => { setUsers(userItems.filter((user) => user.role === "user")); setInvites(inviteItems); setBooks(bookItems ?? []); })
    .catch((error) => setMessage(error instanceof Error ? error.message : "无法读取管理数据。"));
  useEffect(() => { void refresh(); }, []);

  async function createInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const invite = await apiJson<{ code: string }>("/admin/invites", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label: label || null }) });
      setCode(invite.code);
      setLabel("");
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "创建邀请码失败。"); }
  }

  async function revokeInvite(invite: Invite) {
    if (!window.confirm("确定撤销这个邀请码吗？撤销后不能恢复。")) return;
    try { await apiJson(`/admin/invites/${invite.id}/revoke`, { method: "POST" }); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "撤销邀请码失败。"); }
  }

  async function updateLimit(user: User, value: string) {
    const bookImportLimit = Number(value);
    if (!Number.isInteger(bookImportLimit) || bookImportLimit < user.book_import_count) return;
    try {
      await apiJson(`/admin/users/${user.id}/book-import-limit`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ book_import_limit: bookImportLimit }) });
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "调整额度失败。"); }
  }

  async function updateStatus(user: User) {
    const action = user.status === "frozen" ? "unfreeze" : "freeze";
    const label = action === "freeze" ? "冻结" : "恢复";
    if (!window.confirm(`确定${label} ${user.email} 吗？`)) return;
    try {
      await apiJson(`/admin/users/${user.id}/${action}`, { method: "POST" });
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "更新账号状态失败。"); }
  }

  async function resetPassword(user: User) {
    if (!window.confirm(`确定重置 ${user.email} 的密码吗？该用户的所有登录设备将退出。`)) return;
    try {
      const result = await apiJson<{ temporary_password: string }>(`/admin/users/${user.id}/reset-password`, { method: "POST" });
      setTemporaryPassword(result.temporary_password);
      setMessage("已重置密码，请安全地把临时密码交给用户。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "重置密码失败。"); }
  }

  async function publishBook(book: AdminBook) {
    try {
      await apiJson(`/admin/books/${book.id}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rights_confirmed: true }),
      });
      setRightsConfirmed((confirmed) => ({ ...confirmed, [book.id]: false }));
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "发布精选书籍失败。"); }
  }

  async function unpublishBook(book: AdminBook) {
    if (!window.confirm("取消公开后，普通用户将立即无法访问这本书。继续吗？")) return;
    try { await apiJson(`/admin/books/${book.id}/unpublish`, { method: "POST" }); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "取消公开失败。"); }
  }

  const inviteStatus = (invite: Invite) => invite.status === "active" ? "未使用" : invite.status === "used" ? "已使用" : "已撤销";
  return <main className="account-page"><section className="account-card"><Link href="/">← 返回书架</Link><h1>体验账号与邀请码</h1><form onSubmit={createInvite}><label>备注<input value={label} onChange={(event) => setLabel(event.target.value)} /></label><button type="submit">生成一次性邀请码</button></form>{code && <p>新邀请码：<code>{code}</code></p>}{message && <p role="alert">{message}</p>}{temporaryPassword && <p>新的临时密码：<code>{temporaryPassword}</code></p>}<section className="admin-book-management"><h2>精选书架管理</h2>{books.map((book) => <article key={book.id}><p>{book.title || book.filename} · {book.source_format.toUpperCase()} · {book.visibility === "public" ? "已公开" : "未公开"}</p>{book.visibility === "private" ? <><label><input type="checkbox" checked={rightsConfirmed[book.id] ?? false} onChange={(event) => setRightsConfirmed((confirmed) => ({ ...confirmed, [book.id]: event.target.checked }))} /> 我拥有公开传播这本书的权利</label>{book.publication_blockers.map((blocker) => <p className="admin-book-blocker" key={blocker}>{blocker}</p>)}<button type="button" disabled={book.publication_blockers.length > 0 || !rightsConfirmed[book.id]} onClick={() => void publishBook(book)}>发布到精选书架</button></> : <button type="button" onClick={() => void unpublishBook(book)}>取消公开</button>}</article>)}</section><h2>体验用户</h2>{users.map((user) => <article key={user.id}><p>{user.email} · {user.status === "frozen" ? "已冻结" : "正常"} · {user.book_import_count}/{user.book_import_limit} 本</p><label>导入额度<input aria-label={`${user.email} 导入额度`} type="number" min={user.book_import_count} value={quotaDrafts[user.id] ?? String(user.book_import_limit ?? "")} onChange={(event) => setQuotaDrafts((drafts) => ({ ...drafts, [user.id]: event.target.value }))} /></label><button type="button" onClick={() => void updateLimit(user, quotaDrafts[user.id] ?? String(user.book_import_limit ?? ""))}>保存额度</button><button type="button" onClick={() => void updateStatus(user)}>{user.status === "frozen" ? "恢复账号" : "冻结账号"}</button><button type="button" onClick={() => void resetPassword(user)}>重置密码</button></article>)}<h2>邀请码记录</h2>{invites.map((invite) => <article key={invite.id}><p>{invite.label || "未备注"} · {inviteStatus(invite)}{invite.used_by_user_id ? ` · 已由用户 ${invite.used_by_user_id} 使用` : ""}</p>{invite.status === "active" && <button type="button" onClick={() => void revokeInvite(invite)}>撤销邀请码</button>}</article>)}</section></main>;
}

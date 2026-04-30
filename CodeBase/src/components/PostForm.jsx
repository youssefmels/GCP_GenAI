import { useState, useEffect } from "react";
import { getPost, createPost, updatePost } from "../db";

export default function PostForm({ id, onSaved, onCancel }) {
  const isEdit = id !== null;
  const [form, setForm] = useState({ title: "", content: "", author: "" });
  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isEdit) return;
    getPost(id)
      .then((post) => setForm({ title: post.title, content: post.content, author: post.author }))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const handleChange = (e) => setForm((f) => ({ ...f, [e.target.name]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.title.trim() || !form.content.trim() || !form.author.trim()) {
      setError("All fields are required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (isEdit) {
        await updatePost(id, form);
      } else {
        await createPost(form);
      }
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="status">Loading post...</p>;

  return (
    <div className="post-form-wrap">
      <h1 className="page-title">{isEdit ? "Edit Post" : "New Post"}</h1>
      {error && <p className="status error">{error}</p>}
      <form onSubmit={handleSubmit} className="post-form">
        <div className="field">
          <label htmlFor="title">Title</label>
          <input id="title" name="title" value={form.title} onChange={handleChange} placeholder="Post title" />
        </div>
        <div className="field">
          <label htmlFor="author">Author</label>
          <input id="author" name="author" value={form.author} onChange={handleChange} placeholder="Your name" />
        </div>
        <div className="field">
          <label htmlFor="content">Content</label>
          <textarea id="content" name="content" value={form.content} onChange={handleChange} rows={8} placeholder="Write your post..." />
        </div>
        <div className="form-actions">
          <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving..." : isEdit ? "Update Post" : "Publish Post"}
          </button>
        </div>
      </form>
    </div>
  );
}
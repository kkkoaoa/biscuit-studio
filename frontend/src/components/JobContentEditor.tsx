import { ChevronDown, LockKeyhole, Pencil, Save, X } from 'lucide-react';
import { useEffect, useState } from 'react';

type EditableJobContent = {
  script: string;
  storyboard?: string;
  subtitles?: string;
  prompt: string;
};

type JobContentEditorProps = {
  content: EditableJobContent;
  jobId: string;
  canEdit: boolean;
  defaultExpanded: boolean;
  onEditingChange: (jobId: string, isEditing: boolean) => void;
  onSave: (content: Required<EditableJobContent>) => void;
};

export function JobContentEditor({
  content,
  jobId,
  canEdit,
  defaultExpanded,
  onEditingChange,
  onSave,
}: JobContentEditorProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState<Required<EditableJobContent>>({
    script: content.script,
    storyboard: content.storyboard || '',
    subtitles: content.subtitles || '',
    prompt: content.prompt,
  });

  useEffect(() => {
    setIsExpanded(defaultExpanded);
    if (!canEdit) {
      setIsEditing(false);
      onEditingChange(jobId, false);
    }
  }, [canEdit, defaultExpanded, jobId, onEditingChange]);

  const startEditing = () => {
    if (!canEdit) return;
    setDraft({
      script: content.script,
      storyboard: content.storyboard || '',
      subtitles: content.subtitles || '',
      prompt: content.prompt,
    });
    setIsExpanded(true);
    setIsEditing(true);
    onEditingChange(jobId, true);
  };

  const cancelEditing = () => {
    setDraft({
      script: content.script,
      storyboard: content.storyboard || '',
      subtitles: content.subtitles || '',
      prompt: content.prompt,
    });
    setIsEditing(false);
    onEditingChange(jobId, false);
  };

  const saveEditing = () => {
    onSave(draft);
    setIsEditing(false);
    onEditingChange(jobId, false);
  };

  return (
    <section className="job-content">
      <div className="job-content-toolbar">
        <button
          className="content-toggle"
          type="button"
          aria-expanded={isExpanded}
          onClick={() => setIsExpanded(value => !value)}
        >
          <ChevronDown className={isExpanded ? 'is-expanded' : ''} size={15} />
          查看脚本、分镜与字幕稿
        </button>
        {canEdit && !isEditing && (
          <button
            className="edit-content-button"
            type="button"
            onClick={startEditing}
          >
            <Pencil size={13} /> 编辑内容
          </button>
        )}
        {!canEdit && (
          <span className="content-locked">
            <LockKeyhole size={12} /> 已提交，内容已锁定
          </span>
        )}
      </div>

      {isExpanded && (
        <div className="job-content-body">
          {isEditing ? (
            <>
              <label>
                口播脚本
                <textarea
                  value={draft.script}
                  onChange={event =>
                    setDraft(value => ({
                      ...value,
                      script: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                分镜
                <textarea
                  value={draft.storyboard}
                  onChange={event =>
                    setDraft(value => ({
                      ...value,
                      storyboard: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                后期字幕稿
                <textarea
                  value={draft.subtitles}
                  onChange={event =>
                    setDraft(value => ({
                      ...value,
                      subtitles: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Seedance 无字画面提示词
                <textarea
                  className="prompt-editor"
                  value={draft.prompt}
                  onChange={event =>
                    setDraft(value => ({
                      ...value,
                      prompt: event.target.value,
                    }))
                  }
                />
              </label>
              <div className="editor-actions">
                <button
                  className="save-content-button"
                  type="button"
                  onClick={saveEditing}
                >
                  <Save size={14} /> 保存修改
                </button>
                <button
                  className="cancel-content-button"
                  type="button"
                  onClick={cancelEditing}
                >
                  <X size={14} /> 取消
                </button>
              </div>
            </>
          ) : (
            <>
              <strong>口播脚本</strong>
              <pre>{content.script}</pre>
              {content.storyboard && (
                <>
                  <strong>分镜</strong>
                  <pre>{content.storyboard}</pre>
                </>
              )}
              {content.subtitles && (
                <>
                  <strong>后期字幕稿</strong>
                  <pre>{content.subtitles}</pre>
                </>
              )}
              <strong>Seedance 无字画面提示词</strong>
              <p className="prompt-preview">{content.prompt}</p>
            </>
          )}
        </div>
      )}
    </section>
  );
}

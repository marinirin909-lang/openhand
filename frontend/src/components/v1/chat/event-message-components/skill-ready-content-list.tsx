import React from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight } from "lucide-react";
import { I18nKey } from "#/i18n/declaration";
import { SkillReadyItem } from "../event-content-helpers/create-skill-ready-event";
import { MarkdownRenderer } from "../../../features/markdown/markdown-renderer";

interface ParsedSkillContent {
  matchInfo: string | null;
  filePath: string | null;
  body: string;
}

const METADATA_PREFIXES: readonly string[] = [
  "The following information has been included",
  "It may or may not be relevant",
  "Skill location:",
  "(Use this path to resolve",
];

/**
 * Parses skill content into metadata (keyword match info, file path)
 * and the actual skill body.
 */
function parseSkillContent(content: string): ParsedSkillContent {
  const lines = content.split("\n");
  let matchInfo: string | null = null;
  let filePath: string | null = null;
  let bodyStartIndex = 0;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    if (line.startsWith(METADATA_PREFIXES[0])) {
      matchInfo = line.trim();
      bodyStartIndex = i + 1;
    } else if (line.startsWith(METADATA_PREFIXES[2])) {
      filePath = line.replace(METADATA_PREFIXES[2], "").trim();
      bodyStartIndex = i + 1;
    } else if (
      line.startsWith(METADATA_PREFIXES[1]) ||
      line.startsWith(METADATA_PREFIXES[3])
    ) {
      bodyStartIndex = i + 1;
    } else if (line.trim() === "" && i <= bodyStartIndex) {
      bodyStartIndex = i + 1;
    } else {
      break;
    }
  }

  return {
    matchInfo,
    filePath,
    body: lines.slice(bodyStartIndex).join("\n").trim(),
  };
}

function SkillItemExpanded({ content }: { content: string }) {
  const { t } = useTranslation();
  const { matchInfo, filePath, body } = parseSkillContent(content);
  const hasMetadata = matchInfo || filePath;

  return (
    <div className="pl-6 pr-2 pb-2">
      {hasMetadata && (
        <div className="mb-3 text-xs text-neutral-400 space-y-1">
          {matchInfo && <p>{matchInfo}</p>}
          {filePath && (
            <p>
              <span className="text-neutral-500">
                {t(I18nKey.COMMON$PATH)}{" "}
              </span>
              <code className="bg-neutral-800 px-1.5 py-0.5 rounded text-neutral-300">
                {filePath}
              </code>
            </p>
          )}
        </div>
      )}

      {hasMetadata && body && <hr className="border-neutral-700 mb-3" />}

      {body && <MarkdownRenderer>{body}</MarkdownRenderer>}
    </div>
  );
}

interface SkillReadyContentListProps {
  items: SkillReadyItem[];
}

export function SkillReadyContentList({ items }: SkillReadyContentListProps) {
  const { t } = useTranslation();
  const [expandedSkills, setExpandedSkills] = React.useState<
    Record<string, boolean>
  >({});

  const toggleSkill = (name: string) => {
    setExpandedSkills((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  return (
    <div className="flex flex-col gap-1 mt-1">
      <span className="font-bold text-neutral-200 text-sm px-2 py-1">
        {t(I18nKey.SKILLS$TRIGGERED_SKILL_KNOWLEDGE)}
      </span>
      {items.map((item) => {
        const isExpanded = expandedSkills[item.name] || false;

        return (
          <div key={item.name} className="rounded-md overflow-hidden">
            <button
              type="button"
              onClick={() => toggleSkill(item.name)}
              className="w-full py-1.5 px-2 text-left flex items-center gap-2 hover:bg-neutral-700 transition-colors rounded-md cursor-pointer"
            >
              <span className="text-neutral-300">
                {isExpanded ? (
                  <ChevronDown size={14} />
                ) : (
                  <ChevronRight size={14} />
                )}
              </span>
              <span className="font-semibold text-neutral-200 text-sm">
                {item.name}
              </span>
            </button>

            {isExpanded && item.content && (
              <SkillItemExpanded content={item.content} />
            )}
          </div>
        );
      })}
    </div>
  );
}

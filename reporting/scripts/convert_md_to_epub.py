#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tradingagents.reporting import write_report_tree
from tradingagents.default_config import DEFAULT_CONFIG

def convert_md_to_epub(md_path: str):
    md_path = Path(md_path)
    if not md_path.exists():
        print(f"Error: File not found: {md_path}")
        sys.exit(1)

    content = md_path.read_text(encoding="utf-8")

    md_content = content

    import traceback
    try:
        from ebooklib import epub
        import markdown
        HAVE_EPUB = True
    except ImportError:
        HAVE_EPUB = False
    
    if not HAVE_EPUB:
        print("Error: ebooklib or markdown not installed. Install them with:\n  pip install ebooklib markdown")
        sys.exit(1)

    ticker = md_path.stem.split('_')[0]
    header = f"# Trading Analysis Report: {ticker}\n\n"
    
    book = epub.EpubBook()
    book.set_identifier('trading-analysis')
    
    deep = DEFAULT_CONFIG.get("deep_think_llm", "deep")
    quick = DEFAULT_CONFIG.get("quick_think_llm", "quick")
    author_name = f"{deep} & {quick}" if deep != quick else deep
    book.add_author(author_name)
    book.set_title(f'{ticker} Analysis Report')
    book.set_language('en')
    
    html_content = markdown.markdown(md_content, extensions=["tables", "fenced_code"])
    chapter = epub.EpubHtml(title=str(ticker), file_name='chapter.xhtml', content=html_content)
    book.add_item(chapter)
    
    style = '''
    body {
        font-size: 90%;
        line-height: 1.4;
    }
    table {
        border-collapse: collapse;
        width: 100%;
        font-size: 0.9em;
        margin: 1em 0;
    }
    th, td {
        border: 1px solid #aaa;
        padding: 4px 8px;
        text-align: left;
    }
    th {
        background-color: #f0f0f0;
        font-weight: bold;
    }
    '''
    css_item = epub.EpubItem(
        file_name='style.css',
        media_type='text/css',
        content=style
    )
    book.add_item(css_item)
    chapter.add_link(href='style.css', rel='stylesheet', type='text/css')
    book.add_item(chapter)
    book.toc = (chapter,)
    book.spine = ['nav', chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    epub_path = md_path.parent / f"{ticker}.epub"
    epub.write_epub(str(epub_path), book, {})
    print(f"Created: {epub_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert_md_to_epub.py <path/to/complete_report.md>")
        sys.exit(1)
    convert_md_to_epub(sys.argv[1])
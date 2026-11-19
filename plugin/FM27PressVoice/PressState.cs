using System.Collections.Generic;
using UnityEngine.UIElements;

namespace FM27PressVoice;

// JSON alan adları docs/protocol.md ile birebir (snake_case alanlar, IncludeFields ile serileşir).
#pragma warning disable IDE1006
public class PressState
{
    public int v = 1;
    public long seq;
    public string time;
    public bool active;
    public string screen;
    public string event_hint;
    public string question_id;
    public bool ready;
    public int? question_index;
    public int? question_total;
    public string title;
    public string opponent;
    public string competition;
    public string overall_mood;
    public string manager_name;
    public Journalist journalist;
    public List<Journalist> journalists;
    public string game_question;
    public string game_question_raw;
    public List<string> previous_npc_bubbles;
    public List<Category> categories;
    public string override_question_id;
    public Applied last_applied;
    public Dictionary<string, string> context;   // arka plan ekranlarından: tarih, sonraki maç, son haber
    public object match;
}

public class Journalist
{
    public string name;
    public string outlet;
    public string mood;
    public string mood_class;
    public bool active;
}

public class Category
{
    public int index;
    public string title;
    public string sentiment;
    public List<Option> options = new();
}

public class Option
{
    public int index;
    public string text;
    public bool enabled = true;
}

public class Applied
{
    public string question_id;
    public bool ok;
    public string action;
    public string detail;
    public string time;
}

public class QuestionCommand
{
    public int v;
    public string question_id;
    public string text;
}

public class AnswerCommand
{
    public int v;
    public string question_id;
    public int category_index;
    public int option_index;
    public string display_text;
    public bool click = true;
}
#pragma warning restore IDE1006

/// Okuma sırasında bulunan canlı eleman referansları (serileşmez).
internal sealed class PressRefs
{
    public VisualElement QuestionText;           // son NPC balonundaki SIText
    public List<VisualElement> HumanBubbleTexts = new();
    public List<List<OptionRef>> Options = new(); // [kategori][seçenek]
}

internal sealed class OptionRef
{
    public VisualElement Outer;   // SpeakToMeetingAnswerActionButton altındaki ilk SIButton 'StandardButton'
    public VisualElement Inner;   // .speakto-body-header-suggestion-button--action-secondary
    public VisualElement Text;    // seçenek cümlesi SIText
}

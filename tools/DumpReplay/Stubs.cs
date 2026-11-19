// Ui.cs'in referans verdiği Plugin sınıfı yerine sahte (test sırasında SetText çağrılmaz).
namespace FM27PressVoice
{
    internal class Plugin
    {
        internal static Plugin Instance = new();
        internal LogStub Log = new();
    }
    internal class LogStub
    {
        public void LogWarning(object o) => System.Console.Error.WriteLine("W: " + o);
        public void LogInfo(object o) => System.Console.Error.WriteLine("I: " + o);
    }
}

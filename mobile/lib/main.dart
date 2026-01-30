import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:audioplayers/audioplayers.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:permission_handler/permission_handler.dart';

void main() {
  runApp(const NeurolousApp());
}

class NeurolousApp extends StatelessWidget {
  const NeurolousApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Neurolous Client',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        scaffoldBackgroundColor: const Color(0xFFF8FAFC),
      ),
      home: const ChatScreen(),
    );
  }
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _ipController = TextEditingController();
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<Map<String, String>> _messages = [];
  final AudioPlayer _audioPlayer = AudioPlayer();
  late stt.SpeechToText _speech;
  bool _isListening = false;
  bool _isLoading = false;
  bool _isVoiceLoading = false;
  int? _playingIndex;
  String _backendUrl = "http://192.168.1.X:8000";

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
    _loadSettings();
    _requestPermissions();
  }

  @override
  void dispose() {
    _ipController.dispose();
    _textController.dispose();
    _scrollController.dispose();
    _audioPlayer.dispose();
    super.dispose();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _backendUrl = prefs.getString('backend_ip') ?? "http://192.168.1.X:8000";
      _ipController.text = _backendUrl;
    });
    // Load chat history after settings are loaded
    _loadHistory();
  }

  Future<void> _loadHistory() async {
    try {
      final response = await http.get(
        Uri.parse('$_backendUrl/api/history'),
      );

      if (response.statusCode == 200) {
        final List<dynamic> history = jsonDecode(response.body);
        setState(() {
          _messages.clear();
          for (var item in history) {
            _messages.add({
              "role": item['role'] == 'user' ? 'user' : 'bot',
              "text": item['content'] ?? '',
            });
          }
        });
        _scrollToBottom();
      }
    } catch (e) {
      debugPrint("Failed to load history: $e");
    }
  }

  Future<void> _saveSettings() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('backend_ip', _ipController.text);
    setState(() {
      _backendUrl = _ipController.text;
      _messages.clear();
    });
    // Reload history with new backend URL
    _loadHistory();
    if (mounted) Navigator.pop(context);
  }

  Future<void> _requestPermissions() async {
    await [Permission.microphone, Permission.speech].request();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _sendMessage(String text) async {
    if (text.isEmpty) return;

    setState(() {
      _messages.add({"role": "user", "text": text});
      _isLoading = true;
    });
    _textController.clear();
    _scrollToBottom();

    try {
      final response = await http.post(
        Uri.parse('$_backendUrl/chat/text'),
        body: {'message': text},
      );

      if (response.statusCode == 200) {
        String botResponse = response.body;
        setState(() => _messages.add({"role": "bot", "text": botResponse}));
        _scrollToBottom();
        // Auto-play voice for new response
        _playVoice(botResponse, _messages.length - 1);
      } else {
        setState(() => _messages.add({
              "role": "system",
              "text": "Server Error: ${response.statusCode}"
            }));
      }
    } catch (e) {
      setState(() =>
          _messages.add({"role": "system", "text": "Connection Error: $e"}));
    } finally {
      setState(() => _isLoading = false);
      _scrollToBottom();
    }
  }

  Future<void> _playVoice(String text, int index) async {
    try {
      setState(() {
        _isVoiceLoading = true;
        _playingIndex = index;
      });

      await _audioPlayer.stop();
      String audioUrl =
          '$_backendUrl/voice/generate?text=${Uri.encodeComponent(text)}';

      // Listen for when audio starts playing
      _audioPlayer.onPlayerStateChanged.listen((state) {
        if (state == PlayerState.playing) {
          setState(() => _isVoiceLoading = false);
        } else if (state == PlayerState.completed || state == PlayerState.stopped) {
          setState(() {
            _isVoiceLoading = false;
            _playingIndex = null;
          });
        }
      });

      await _audioPlayer.play(UrlSource(audioUrl));
    } catch (e) {
      debugPrint("Audio Error: $e");
      setState(() {
        _isVoiceLoading = false;
        _playingIndex = null;
      });
    }
  }

  void _listen() async {
    if (!_isListening) {
      bool available = await _speech.initialize(
        onStatus: (status) => debugPrint('Speech status: $status'),
        onError: (error) => debugPrint('Speech error: $error'),
      );
      if (available) {
        setState(() => _isListening = true);
        _speech.listen(
          onResult: (val) {
            if (val.finalResult) {
              setState(() => _isListening = false);
              _sendMessage(val.recognizedWords);
            }
          },
          listenFor: const Duration(seconds: 30),
          pauseFor: const Duration(seconds: 3),
        );
      }
    } else {
      setState(() => _isListening = false);
      _speech.stop();
    }
  }

  void _showSettingsDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Backend Configuration"),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              "Enter your Mac's local network IP address:",
              style: TextStyle(fontSize: 12, color: Colors.grey),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _ipController,
              decoration: const InputDecoration(
                labelText: "Backend URL",
                hintText: "http://192.168.1.50:8000",
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("Cancel"),
          ),
          ElevatedButton(
            onPressed: _saveSettings,
            child: const Text("Save"),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(Map<String, String> msg, int index) {
    bool isUser = msg['role'] == 'user';
    bool isSystem = msg['role'] == 'system';
    bool isBot = msg['role'] == 'bot';
    bool isCurrentlyPlaying = _playingIndex == index;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(12),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.8,
        ),
        decoration: BoxDecoration(
          color: isSystem
              ? Colors.red.shade50
              : isUser
                  ? Colors.indigo.shade50
                  : Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSystem
                ? Colors.red.shade200
                : isUser
                    ? Colors.indigo.shade100
                    : Colors.grey.shade200,
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.05),
              blurRadius: 4,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              msg['text']!,
              style: TextStyle(
                fontSize: 16,
                color: isSystem ? Colors.red.shade700 : Colors.black,
              ),
            ),
            // Voice play button for bot messages
            if (isBot) ...[
              const SizedBox(height: 8),
              GestureDetector(
                onTap: () => _playVoice(msg['text']!, index),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: isCurrentlyPlaying
                        ? const Color(0xFF4F46E5).withOpacity(0.1)
                        : Colors.grey.shade100,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(
                      color: isCurrentlyPlaying
                          ? const Color(0xFF4F46E5)
                          : Colors.grey.shade300,
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (_isVoiceLoading && isCurrentlyPlaying)
                        const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            valueColor: AlwaysStoppedAnimation<Color>(
                              Color(0xFF4F46E5),
                            ),
                          ),
                        )
                      else
                        Icon(
                          isCurrentlyPlaying ? Icons.volume_up : Icons.play_arrow,
                          size: 16,
                          color: isCurrentlyPlaying
                              ? const Color(0xFF4F46E5)
                              : Colors.grey.shade600,
                        ),
                      const SizedBox(width: 4),
                      Text(
                        isCurrentlyPlaying
                            ? (_isVoiceLoading ? "Loading..." : "Playing")
                            : "Play Voice",
                        style: TextStyle(
                          fontSize: 12,
                          color: isCurrentlyPlaying
                              ? const Color(0xFF4F46E5)
                              : Colors.grey.shade600,
                          fontWeight: isCurrentlyPlaying
                              ? FontWeight.bold
                              : FontWeight.normal,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          "Neurolous",
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
        ),
        centerTitle: true,
        flexibleSpace: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              colors: [Color(0xFF06B6D4), Color(0xFF4F46E5)],
            ),
          ),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white),
            onPressed: _loadHistory,
            tooltip: "Reload History",
          ),
          IconButton(
            icon: const Icon(Icons.settings, color: Colors.white),
            onPressed: _showSettingsDialog,
          )
        ],
      ),
      body: Column(
        children: [
          // Messages list
          Expanded(
            child: _messages.isEmpty
                ? Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          Icons.chat_bubble_outline,
                          size: 64,
                          color: Colors.grey.shade300,
                        ),
                        const SizedBox(height: 16),
                        Text(
                          "Hold the button below to speak\nor type a message",
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.grey.shade500,
                            fontSize: 16,
                          ),
                        ),
                      ],
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(16),
                    itemCount: _messages.length,
                    itemBuilder: (context, index) {
                      return _buildMessageBubble(_messages[index], index);
                    },
                  ),
          ),

          // Loading indicator
          if (_isLoading)
            const LinearProgressIndicator(
              minHeight: 2,
              backgroundColor: Color(0xFFE0E7FF),
              valueColor: AlwaysStoppedAnimation<Color>(Color(0xFF4F46E5)),
            ),

          // Input area
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.05),
                  blurRadius: 10,
                  offset: const Offset(0, -4),
                ),
              ],
            ),
            child: SafeArea(
              child: Column(
                children: [
                  // Text input row
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _textController,
                          decoration: InputDecoration(
                            hintText: "Type a message...",
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(24),
                              borderSide: BorderSide(color: Colors.grey.shade300),
                            ),
                            contentPadding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 12,
                            ),
                          ),
                          onSubmitted: _sendMessage,
                        ),
                      ),
                      const SizedBox(width: 8),
                      IconButton(
                        onPressed: () => _sendMessage(_textController.text),
                        icon: const Icon(Icons.send),
                        color: const Color(0xFF4F46E5),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),

                  // Voice button
                  GestureDetector(
                    onLongPress: _listen,
                    onLongPressUp: () {
                      _speech.stop();
                      setState(() => _isListening = false);
                    },
                    child: Container(
                      height: 56,
                      width: double.infinity,
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          colors: _isListening
                              ? [const Color(0xFFEC4899), const Color(0xFFEF4444)]
                              : [const Color(0xFF06B6D4), const Color(0xFF4F46E5)],
                        ),
                        borderRadius: BorderRadius.circular(28),
                        boxShadow: [
                          BoxShadow(
                            color: Colors.indigo.withOpacity(0.4),
                            blurRadius: 8,
                            offset: const Offset(0, 4),
                          ),
                        ],
                      ),
                      child: Center(
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              _isListening ? Icons.mic : Icons.mic_none,
                              color: Colors.white,
                            ),
                            const SizedBox(width: 8),
                            Text(
                              _isListening ? "Listening..." : "Hold to Speak",
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                fontSize: 16,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

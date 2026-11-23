package research;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.microsoft.z3.Context;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import language.actions.DelayTimedAction;
import language.actions.ResetLogicalTimedAction;
import language.words.DelayTimedWord;
import language.words.LogicalTimedWord;
import language.words.ResetLogicalTimedWord;
import learning.teachers.Teacher;
import run.ClockValuation;
import ta.Action;
import ta.Clock;
import ta.NTA;
import ta.TA;
import ta.Value;
import tools.FileIO.TAUtil;
import tools.Tuple.Triplet;

public final class TestTeacher extends Teacher {
    private final BufferedReader input = new BufferedReader(new InputStreamReader(System.in));
    private int membershipQueries;
    private int equivalenceQueries;

    public TestTeacher(NTA target, Context solver) {
        super(target, solver);
    }

    public static void emit(JSONObject message) {
        System.out.println("\n@@BRIDGE " + message.toJSONString());
        System.out.flush();
    }

    private JSONObject read() {
        try {
            JSONObject message = JSON.parseObject(input.readLine());
            if ("stop".equals(message.getString("op"))) System.exit(0);
            return message;
        } catch (IOException error) {
            throw new UncheckedIOException(error);
        }
    }

    private void reply(boolean label) {
        membershipQueries++;
        JSONObject message = new JSONObject();
        message.put("label", label);
        emit(message);
    }

    @Override
    public boolean MembershipQuery(LogicalTimedWord word) {
        Map<Action, Set<Clock>> resets = resets(getTargetNTA());
        List<Set<Clock>> clockSets = new ArrayList<>();
        for (var action : word) {
            clockSets.add(resets.getOrDefault(action.getAction(), Set.of()));
        }
        JSONObject message = new JSONObject();
        message.put("word", encode(word.toResetLogicalTimedWord(clockSets).toDelayTimedWord()));
        emit(message);
        JSONObject response = read();
        if ("cached".equals(response.getString("op"))) {
            return response.getBooleanValue("label");
        }
        boolean label = super.MembershipQuery(word);
        reply(label);
        return label;
    }

    @Override
    public Triplet<Boolean, ResetLogicalTimedWord, Boolean> EquivalenceQuery(NTA hypothesis) {
        equivalenceQueries++;
        JSONArray parts = new JSONArray();
        for (TA component : hypothesis.getTA_list()) {
            parts.add(TAUtil.buildJsonObjectFromTA(component));
        }
        JSONObject message = new JSONObject();
        message.put("hypothesis", parts);
        emit(message);
        while (true) {
            JSONObject response = read();
            JSONArray word = response.getJSONArray("word");
            if ("ce".equals(response.getString("op"))) {
                return new Triplet<>(false, logical(word, getTargetNTA()),
                                     response.getBooleanValue("positive"));
            }
            reply(accepts(word, getTargetNTA()));
        }
    }

    @Override
    public Triplet<Integer, Integer, Integer> snapshotQueryCount() {
        return new Triplet<>(0, membershipQueries, equivalenceQueries);
    }

    private static Map<Action, Set<Clock>> resets(NTA network) {
        Map<Action, Set<Clock>> result = new HashMap<>();
        for (TA component : network.getTA_list()) {
            for (Action action : component.getAllActions()) {
                result.computeIfAbsent(action, key -> new HashSet<>()).addAll(component.getAllClocks());
            }
        }
        return result;
    }

    private static ResetLogicalTimedWord logical(JSONArray word, NTA network) {
        Map<Action, Set<Clock>> resets = resets(network);
        ClockValuation valuation = new ClockValuation(network.getAllClocks());
        ResetLogicalTimedWord result = new ResetLogicalTimedWord();
        for (int i = 0; i < word.size(); i++) {
            JSONArray item = word.getJSONArray(i);
            Action action = Action.getAction(item.getString(0));
            valuation = valuation.delay(new Value(item.getLongValue(1), item.getLongValue(2)));
            Set<Clock> clocks = resets.getOrDefault(action, Set.of());
            result.attend(new ResetLogicalTimedAction(action, valuation, clocks));
            valuation = valuation.reset(clocks);
        }
        return result;
    }

    private static JSONArray encode(DelayTimedWord word) {
        JSONArray result = new JSONArray();
        for (DelayTimedAction action : word) {
            var delay = action.getDelayTime().getValue();
            JSONArray item = new JSONArray();
            item.add(action.getAction().getName());
            item.add(delay.getNumerator());
            item.add(delay.getDenominator());
            result.add(item);
        }
        return result;
    }

    public static boolean accepts(JSONArray word, NTA network) {
        return network.ifContain(logical(word, network).toLogicalTimedWord()).p0();
    }
}

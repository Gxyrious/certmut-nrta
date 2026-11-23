import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import java.nio.file.Files;
import java.nio.file.Path;
import learning.LearningSetting;
import learning.teachers.TeacherSetting;
import research.TestTeacher;
import ta.NTA;
import ta.TA;
import tools.ExtendSolver;
import tools.FileIO.TAUtil;
import verify.Verifiers.ZoneVerifier;

public class Driver {
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "learn" -> {
                LearningSetting.LEARNING_LOG_LEVEL = LearningSetting.LearningLogLevel.QUIET;
                LearningSetting.SAVE_HYPOTHESIS = false;
                LearningSetting.RUN_CASE_TIMEOUT_SECONDS = 0;
                TeacherSetting.VERIFY_CANONICAL_TABLE_SOLVE = true;
                CompositionLearningMain.runCase(args[1]);
            }
            case "evaluate" -> evaluate(Path.of(args[1]), Path.of(args[2]), Path.of(args[3]));
            default -> throw new IllegalArgumentException(args[0]);
        }
    }

    private static NTA load(Path directory, ExtendSolver solver) throws Exception {
        try (var files = Files.list(directory)) {
            var paths = files.filter(p -> p.getFileName().toString().matches("[PH].*\\.json"))
                             .sorted().toList();
            TA[] components = new TA[paths.size()];
            for (int i = 0; i < paths.size(); i++) {
                components[i] = TAUtil.buildTAFromJson(paths.get(i).toString(), solver);
            }
            return new NTA(components).makeComplete(solver);
        }
    }

    private static void evaluate(Path targetPath, Path hypothesisPath, Path bank) throws Exception {
        try (var solver = new ExtendSolver(); var reader = Files.newBufferedReader(bank)) {
            NTA target = load(targetPath, solver);
            NTA hypothesis = load(hypothesisPath, solver);
            int[] totals = new int[2];
            int[] agreements = new int[2];
            for (String line; (line = reader.readLine()) != null;) {
                JSONObject item = JSON.parseObject(line);
                int label = item.getBooleanValue("target_label") ? 1 : 0;
                int predicted = TestTeacher.accepts(item.getJSONArray("word"), hypothesis) ? 1 : 0;
                totals[label]++;
                if (predicted == label) agreements[label]++;
            }
            double valid = (double) agreements[1] / totals[1];
            double rejected = (double) agreements[0] / totals[0];
            boolean equivalent = new ZoneVerifier(solver).checkLanguageEquivalence(target, hypothesis).p0();
            JSONObject result = new JSONObject();
            result.put("behavior_agreement", (double) (agreements[0] + agreements[1]) / (totals[0] + totals[1]));
            result.put("valid_agreement", valid);
            result.put("reject_agreement", rejected);
            result.put("strict_eq", equivalent ? 1 : 0);
            TestTeacher.emit(result);
        }
    }
}

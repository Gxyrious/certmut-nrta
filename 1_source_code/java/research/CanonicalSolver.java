package research;

import com.microsoft.z3.BitVecExpr;
import com.microsoft.z3.BitVecNum;
import com.microsoft.z3.BoolExpr;
import com.microsoft.z3.Model;
import com.microsoft.z3.Solver;
import com.microsoft.z3.Status;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import tools.ExtendSolver;

public final class CanonicalSolver {
    public record Result(Status status, Model model, String input) {}

    public static Result solve(ExtendSolver context, List<BitVecExpr> objectives,
                               BoolExpr... constraints) {
        Solver solver = context.mkSolver();
        ExtendSolver.applyRandomSeed(context, solver);
        solver.add(constraints);
        String input = solver.toString();
        Status status = solver.check();
        if (status != Status.SATISFIABLE) return new Result(status, null, input);
        Model model = solver.getModel();
        Set<Integer> decided = new HashSet<>();
        for (BitVecExpr objective : objectives) {
            for (int i = objective.getSortSize() - 1; i >= 0; i--) {
                BitVecExpr bit = (BitVecExpr) context.mkExtract(i, i, objective).simplify();
                if (bit instanceof BitVecNum || !decided.add(bit.getId())) continue;
                BoolExpr zero = context.mkEq(bit, context.bvFalse);
                boolean chooseZero = context.getBvValue(bit, model).signum() == 0;
                if (!chooseZero) {
                    switch (solver.check(zero)) {
                        case SATISFIABLE -> {
                            chooseZero = true;
                            model = solver.getModel();
                        }
                        case UNSATISFIABLE -> {}
                        case UNKNOWN -> throw new IllegalStateException(solver.getReasonUnknown());
                    }
                }
                solver.add(chooseZero ? zero : context.mkEq(bit, context.bvTrue));
            }
        }
        return new Result(solver.check(), solver.getModel(), input);
    }
}

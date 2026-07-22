package ai.nivesh.app.ui.goals;

import ai.nivesh.app.data.repo.GoalsRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class GoalsViewModel_Factory implements Factory<GoalsViewModel> {
  private final Provider<GoalsRepository> repoProvider;

  public GoalsViewModel_Factory(Provider<GoalsRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public GoalsViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static GoalsViewModel_Factory create(Provider<GoalsRepository> repoProvider) {
    return new GoalsViewModel_Factory(repoProvider);
  }

  public static GoalsViewModel newInstance(GoalsRepository repo) {
    return new GoalsViewModel(repo);
  }
}
